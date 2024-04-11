import numpy as np
import torch
from librep.estimators.ae.torch.models.topological_ae.topological_ae import (
    TopologicallyRegularizedAutoencoder
)
from librep.transforms.topo_ae_model import ConvTAEModule
from tqdm import tqdm
from sklearn.model_selection import train_test_split
from librep.base.transform import Transform
from librep.config.type_definitions import ArrayLike
from torch.optim import Adam
import matplotlib.pyplot as plt
import pickle
import shutil
from copy import deepcopy
from torch.utils.data import TensorDataset, DataLoader
import os

class TopologicalDimensionalityReductionRemade(Transform):

    def __init__(
        self,
        # Autoencoder model
        ae_topo_lambda=1.,
        ae_conv_num=2,
        ae_fc_num=2,
        ae_conv_kernel=3,
        ae_conv_stride=1,
        ae_conv_padding=0,
        ae_conv_pooling_type='none',
        ae_conv_pooling_kernel=2,
        ae_conv_pooling_stride=2,
        ae_conv_groups=1,
        ae_dropout=0.2,
        # Latent dimension
        ae_encoding_size=2,
        # Training
        patience=10,
        num_epochs=20000,
        min_epochs=100,
        batch_size=64,
        cuda_device_name='cuda:0',
        file_to_load=None,
        save_dir='data/',
        save_tag=0,
        save_frequency=None,
        verbose=False
    ):
        self.ae_topo_lambda = ae_topo_lambda
        self.ae_conv_num = ae_conv_num
        self.ae_fc_num = ae_fc_num
        self.ae_conv_kernel = ae_conv_kernel
        self.ae_conv_stride = ae_conv_stride
        self.ae_conv_padding = ae_conv_padding
        self.ae_conv_pooling_type = ae_conv_pooling_type
        self.ae_conv_pooling_kernel = ae_conv_pooling_kernel
        self.ae_conv_pooling_stride = ae_conv_pooling_stride
        self.ae_conv_groups = ae_conv_groups
        self.ae_encoding_size = ae_encoding_size
        self.ae_dropout = ae_dropout
        # ------------------------------

        self.file_to_load = file_to_load
        self.save_dir = save_dir
        self.save_tag = save_tag
        self.save_frequency = save_frequency
        self.patience = patience
        self.num_epochs = num_epochs
        self.min_epochs = min_epochs
        # self.model_lambda = lam
        # self.model_latent_dim = latent_dim
        self.verbose = verbose
        
        # Setting cuda device
        self.cuda_device = torch.device(cuda_device_name)
        self.batch_size = batch_size
        
        self.current = {
            'epoch': 0,
            'train_recon_error': None,
            'train_topo_error': None,
            'train_error': None,
            'val_recon_error': None,
            'val_topo_error': None,
            'val_error': None,
            'last_error': None
        }
        self.history = {
            'epoch': [],
            'train_recon_error': [],
            'train_topo_error': [],
            'train_error': [],
            'val_recon_error': [],
            'val_topo_error': [],
            'val_error': []
        }
    
    def __one_epoch(self, data_loader: DataLoader, train_mode=True):
        cumulative_ae_loss = 0
        cumulative_topo_loss = 0
        cumulative_loss = 0
        epoch_loss_counter = 0
        for inputs, _ in data_loader:
            inputs = inputs.to(self.cuda_device)
            if train_mode:
                self.model.train()
                # loss, loss_components = self.model(inputs)
                loss, reconst_loss, topo_loss = self.model(inputs)
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()
            else:
                self.model.eval()
                # loss, loss_components = self.model(inputs)
                loss, reconst_loss, topo_loss = self.model(inputs)
            cumulative_loss += loss.item() * inputs.size(0)
            cumulative_ae_loss += reconst_loss.item() * inputs.size(0)
            if self.ae_topo_lambda > 0:
                cumulative_topo_loss += topo_loss.item() * inputs.size(0)
            else:
                cumulative_topo_loss = 0
            epoch_loss_counter += 1
        return (
            cumulative_loss / epoch_loss_counter,
            cumulative_ae_loss / epoch_loss_counter,
            cumulative_topo_loss / epoch_loss_counter
        )



    def fit(self, X: ArrayLike, y: ArrayLike = None, X_val: ArrayLike = None, y_val: ArrayLike = None):
        if X_val is None:
            X, X_val, y, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
        
        # Computing input dimensions for the model
        # in the second dim of X.shape
        # ----------------------------------------------
        # When the input is 2d:
        # ----------------------------------------------
        number_of_dimensions = len(X.shape)
        if number_of_dimensions == 2:
            # 1 means 1 channel
            self.input_shape = (-1, 1, X.shape[1])
            ae_input_dims = (1, X.shape[1])
        elif number_of_dimensions == 3:
            self.input_shape = (-1, X.shape[1], X.shape[2])
            ae_input_dims = (X.shape[1], X.shape[2])
        else:
            raise ValueError('The input data has to be 2d or 3d')
        # ----------------------------------------------


        # original_dim = X.shape[-1]
        # original_dimensionality = X.shape[-1]
        # # Setting self.input_shape
        # self.input_shape = (-1, 1, original_dim)
        # # In case of no convolutional layers (input is 1d)
        # if self.ae_conv_num == 0:
        #     self.input_shape = (-1, original_dim)
        # # Setting ae_kwargs['input_dims']
        # self.ae_kwargs['input_dims'] = (1, original_dim)
        # # ----------------------------------------------
        # # When the input is 3d (length, dim1, dim2): TODO
        # # ----------------------------------------------
        # if len(X.shape) == 3:
        #     self.input_shape = (-1, X.shape[1], original_dim)
        #     self.ae_kwargs['input_dims'] = (X.shape[1], original_dim)

        # Modifying the data into the input_shape
        x_train = torch.reshape(torch.Tensor(X), self.input_shape).to(torch.float32)
        y_train = torch.Tensor(np.array(y))
        x_val = torch.reshape(torch.Tensor(X_val), self.input_shape).to(torch.float32)
        y_val = torch.Tensor(np.array(y_val))

        # Initializing all
        # self.model = TopologicallyRegularizedAutoencoder(
        #     autoencoder_model=self.model_name,
        #     lam=self.model_lambda, ae_kwargs=self.ae_kwargs
        # )
        self.model = ConvTAEModule(
            info={
                'ae_topo_lambda': self.ae_topo_lambda,
                'ae_conv_num': self.ae_conv_num,
                'ae_fc_num': self.ae_fc_num,
                'ae_conv_kernel': self.ae_conv_kernel,
                'ae_conv_stride': self.ae_conv_stride,
                'ae_conv_padding': self.ae_conv_padding,
                'ae_conv_pooling_type': self.ae_conv_pooling_type,
                'ae_conv_pooling_kernel': self.ae_conv_pooling_kernel,
                'ae_conv_pooling_stride': self.ae_conv_pooling_stride,
                'ae_conv_groups': self.ae_conv_groups,
                'ae_encoding_size': self.ae_encoding_size,
                'ae_dropout': self.ae_dropout,
                'input_channels': ae_input_dims[0],
                'input_size': ae_input_dims
            }
        )
        if self.file_to_load:
            file_handler = open(self.file_to_load, 'rb')
            model_state_dict = pickle.load(file_handler)
            file_handler.close()
            self.model.load_state_dict(model_state_dict)
            self.model.eval()
            self.model = self.model.to(self.cuda_device)
            return
        self.model = self.model.to(self.cuda_device)
        # Optimizer
        # self.optimizer = Adam(self.model.parameters(), lr=1e-3, weight_decay=1e-5)
        self.optimizer = Adam(
            self.model.parameters()
            # lr=self.optimizer_lr,
            # weight_decay=self.optimizer_weight_decay
            )
        
        # Setting data loaders
        train_data_loader = DataLoader(
            dataset=TensorDataset(x_train, y_train),
            batch_size=self.batch_size,
            shuffle=True,
            # drop_last=True
        )
        val_data_loader = DataLoader(
            dataset=TensorDataset(x_val, y_val),
            batch_size=self.batch_size,
            shuffle=True,
            # drop_last=True
        )
        patience_counter = 0
        loss_threshold = np.inf
        # Preparing for plot
        self.train_final_error = []
        self.train_recon_error = []
        self.train_topo_error = []

        self.val_final_error = []
        self.val_recon_error = []
        self.val_topo_error = []
        # Setting cuda
        # cuda0 = torch.device('cuda:0')
        
        print('CURDIR', os.path.abspath(os.path.curdir))
        
        for epoch in tqdm(range(self.num_epochs)):
            patience_counter += 1
            # Set current values
            self.current['epoch'] = self.current['epoch'] + 1
            # Train epoch
            epoch_loss, epoch_ae_loss, epoch_topo_loss = self.__one_epoch(train_data_loader, train_mode=True)
            self.current['train_recon_error'] = epoch_ae_loss
            self.current['train_topo_error'] = epoch_topo_loss
            self.current['train_error'] = epoch_loss
            # Validation epoch
            epoch_loss, epoch_ae_loss, epoch_topo_loss = self.__one_epoch(val_data_loader, train_mode=False)
            self.current['val_recon_error'] = epoch_ae_loss
            self.current['val_topo_error'] = epoch_topo_loss
            self.current['val_error'] = epoch_loss
            # Set history values
            self.history['epoch'].append(self.current['epoch'])
            self.history['train_recon_error'].append(self.current['train_recon_error'])
            self.history['train_topo_error'].append(self.current['train_topo_error'])
            self.history['train_error'].append(self.current['train_error'])
            self.history['val_recon_error'].append(self.current['val_recon_error'])
            self.history['val_topo_error'].append(self.current['val_topo_error'])
            self.history['val_error'].append(self.current['val_error'])
            # Set the loss value
            loss_per_epoch = self.current['val_error']
            # ae_loss_per_epoch = self.current['val_recon_error']
            # topo_loss_per_epoch = self.current['val_topo_error']
            
            # Check if loss is nan
            if np.isnan(loss_per_epoch):
                if self.verbose:
                    print('Loss is nan, stopping the training')
                break

            # If this model beats the better found until now:
            if loss_per_epoch < loss_threshold:
                patience_counter = 0
                # Save the model_state
                self.model_best_state_dict = deepcopy(self.model.state_dict())
                # Update max_loss
                loss_threshold = loss_per_epoch
                # Save the model
                if self.save_frequency == 'best':
                    os.makedirs(self.save_dir, exist_ok=True)
                    with open(f'{self.save_dir}/{self.save_tag}_epoch_{epoch}.pkl', 'wb') as f:
                        pickle.dump(self.model_best_state_dict, f)
                
            # If verbose, print the results for the current epoch
            if self.verbose:
                print(f'Epoch:{epoch+1}, P:{patience_counter}, V Loss:{self.current["val_error"]:.4f}, Loss-ae:{self.current["val_recon_error"]:.4f}, Loss-topo:{self.current["val_topo_error"]:.4f}')
                print(f'Epoch:{epoch+1}, P:{patience_counter}, T Loss:{self.current["train_error"]:.4f}, Loss-ae:{self.current["train_recon_error"]:.4f}, Loss-topo:{self.current["train_topo_error"]:.4f}')
            # Handle patience
            if epoch >= self.min_epochs and self.patience and patience_counter > self.patience:
                break
        self.model.load_state_dict(self.model_best_state_dict)
        if self.save_frequency:
            with open(f'{self.save_dir}/{self.save_tag}_history.sml', 'wb') as f:
                pickle.dump(self.history, f)

    # def plot_training(self, title_plot=None):
    #     fig, ax = plt.subplots(figsize=(10,10))
    #     ax.set_title('Training')
    #     if title_plot:
    #         ax.set_title(title_plot)
    #     ax.plot(self.history['train_recon_error'], label='reconstruction error - train', color='red')
    #     ax.plot(self.history['val_recon_error'], label='reconstruction error - val', color='orange')
    #     ax.set_xlabel('Epoch')
    #     ax.set_ylabel("Reconstruction error", color="red", fontsize=14)
    #     ax.legend(loc=2)
    #     ax.set_ylim(bottom=0)

    #     ax2 = ax.twinx()
    #     ax2.plot(self.history['train_topo_error'], label='Topological error - train', color='blue')
    #     ax2.plot(self.history['val_topo_error'], label='Topological error - val', color='black')
    #     ax2.set_ylabel("Topological error", color="blue", fontsize=14)
    #     ax2.legend(loc=1)
    #     ax2.set_ylim(bottom=0)
    #     plt.grid()
    #     plt.show()
    
    # def save(self, save_dir='data/', tag=None):
    #     model_name = self.model_name
    #     model_lambda = self.model_lambda
    #     # model_start_dim = self.model_start_dim
    #     model_latent_dim = self.model_latent_dim
    #     model_epc = self.current['epoch']
    #     filename = '{}_{}-{}_{}_{}.pkl'.format(
    #         model_name, model_lambda,
    #         # model_start_dim,
    #         model_latent_dim,
    #         model_epc, self.save_tag)
    #     full_dir = self.save_dir + filename
    #     filehandler = open(full_dir, 'wb')
    #     pickle.dump(self, filehandler)
    #     filehandler.close()
    #     return full_dir
    
    # def partial_save(self, name=None, reuse_file=None):
    #     model_name = self.model_name
    #     model_lambda = self.model_lambda
    #     # model_start_dim = self.model_start_dim
    #     model_latent_dim = self.model_latent_dim
    #     model_epc = self.num_epochs
    #     model_tag = self.save_tag
    #     filename = '{}_{}-{}_{}_{}_ep{}'.format(
    #         model_name, model_lambda,
    #         # model_start_dim,
    #         model_latent_dim,
    #         model_epc, model_tag, self.current['epoch'])
    #     if name:
    #         filename = name
    #     full_dir = self.save_dir + filename
    #     if reuse_file:
    #         shutil.copyfile(self.save_dir + reuse_file, full_dir)
    #         return
    #     torch.save({
    #         'model_state_dict': self.model.state_dict(),
    #         'optimizer_state_dict': self.optimizer.state_dict()
    #     }, full_dir)
    
    # def partial_load(self, epoch=250, name=None):
    #     model_name = self.model_name
    #     model_lambda = self.model_lambda
    #     # model_start_dim = self.model_start_dim
    #     model_latent_dim = self.model_latent_dim
    #     model_epc = self.num_epochs
    #     model_tag = self.save_tag
    #     filename = '{}_{}-{}_{}_{}_ep{}'.format(
    #         model_name, model_lambda,
    #         # model_start_dim,
    #         model_latent_dim,
    #         model_epc, model_tag, epoch)
    #     if name:
    #         filename = name
    #     full_dir = self.save_dir + filename
    #     checkpoint = torch.load(full_dir)
    #     self.model.load_state_dict(checkpoint['model_state_dict'])
    #     self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])

    # def load(self, filename='data/test.pkl'):
    #     filehandler = open(filename, 'rb')
    #     self = pickle.load(filehandler)
    #     filehandler.close()
    #     print('Loaded ', filename)
    
    # TODO
    def transform(self, X: ArrayLike):
        # Setting cuda
        cuda0 = torch.device('cuda:0')
        self.model.eval()
        reshaped_data = np.reshape(X, self.input_shape)
        in_tensor = torch.tensor(reshaped_data, device=cuda0).to(torch.float32)
        return self.model.encoder(in_tensor).cpu().detach().numpy()
    
    def inverse_transform(self, X: ArrayLike):
        # Setting cuda
        cuda0 = torch.device('cuda:0')
        self.model.eval()
        reshaped_data = np.reshape(X, (-1, 1, X.shape[-1]))
        in_tensor = torch.tensor(reshaped_data, device=cuda0).to(torch.float32)
        decoded = self.model.decoder(in_tensor).cpu().detach().numpy()
        return np.reshape(decoded, (X.shape[0], -1))

    # def transform_and_back(self, X: ArrayLike, plot_function):
    #     self.model.eval()
    #     reshaped_data = np.reshape(X, self.input_shape)
    #     in_tensor = torch.Tensor(reshaped_data).float()
    #     X_encoded = self.model.encode(in_tensor).detach().numpy()
    #     plot_function(X, X_encoded)
    #     return 
    
    # def analize_patience(self, data):
    #     patiences = []
    #     patience = 0
    #     p = patience
    #     max_loss = np.max(data) + 1
    #     for index in range(1, len(data)):
    #         # print(index, data[index], p)
    #         if data[index] < max_loss:
    #             max_loss = data[index]
    #             p = patience
    #         else:
    #             if p == 0:
    #                 # print('PATIENCE', patience,' found in index', index, 'with value', data[index])
    #                 patiences.append(index)
    #                 patience +=1
    #                 p += 1
    #             p -= 1
    #     return (data, patiences)


# class ConvTAETransform2(TopologicalDimensionalityReduction):
#     def __init__(self,
#                  model_name='ConvTAE_def',
#                  model_lambda=1,
#                  patience=None,
#                  num_epochs=2000,
#                  min_epochs=100,
#                  latent_dim=2,
#                  batch_size=64,
#                  cuda_device_name='cuda:0',
#                  extra_properties={},
#                  file_to_load=None,
#                  save_dir='data/', save_tag=0, save_frequency=None):
#         ae_kwargs = {
#             'latent_dim': latent_dim,
#             'optimizer_weight_decay': 0,
#             'optimizer_lr': 1e-5
#         }
#         ae_kwargs.update(extra_properties)
#         super().__init__(
#             ae_model=model_name,
#             ae_kwargs=ae_kwargs,
#             lam=model_lambda,
#             patience=patience,
#             num_epochs=num_epochs,
#             min_epochs=min_epochs,
#             batch_size=batch_size,
#             cuda_device_name=cuda_device_name,
#             latent_dim=latent_dim,
#             file_to_load=file_to_load,
#             save_dir=save_dir,
#             save_tag=save_tag,
#             save_frequency=save_frequency
#         )
