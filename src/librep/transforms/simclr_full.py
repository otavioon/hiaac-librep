from librep.estimators.simclr.torch.simclr_full_estimator import Simclr_Full_Estimator
import librep.estimators.simclr.torch.simclr_utils as s_utils
from librep.base.transform import Transform
import copy,os
import torch

class SimCLR_full(Transform):
        def __init__(self,dataset,
                 input_shape,
                 n_components,   
                 batch_size_head,
                 transform_funcs,
                 temperature_head,
                 epochs_head,
                 patience,
                 min_delta,
                 device,
                 save_reducer,
                 save_model,
                 verbose,                 
                 total_epochs,
                 batch_size,
                 lr):
            self.input_shape=input_shape
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            
            self.full_model=Simclr_Full_Estimator(dataset=dataset,
                                                      input_shape=input_shape,
                        n_components=n_components,
                        batch_size_head=batch_size_head,
                        transform_funcs=transform_funcs,
                        temperature_head=temperature_head, 
                        epochs_head=epochs_head,
                                                      patience=patience,
                                                      min_delta=min_delta,
                                                      save_reducer=save_reducer,
                                                      
                                                      
                        device=device,                              
                        save_model=save_model,
                        verbose=verbose,
                        total_epochs=total_epochs,
                        batch_size=batch_size,
                        lr=lr)


        def fit(self,X, y = None, X_val=None, y_val = None):
            self.full_model.fit(X,y,X_val,y_val)
            self.model=self.full_model.model.simclr_head
            return self


        def transform(self, X):
            X = s_utils.resize_data(X, self.input_shape)
            intermediate_model = copy.deepcopy(self.model.base_model)
            test_data = torch.tensor(X, dtype=torch.float32).to(self.device)
            embeddings = intermediate_model(test_data).cpu().detach().numpy()
            return embeddings


