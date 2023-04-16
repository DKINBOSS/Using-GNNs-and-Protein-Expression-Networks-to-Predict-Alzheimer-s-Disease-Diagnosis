# -*- coding: utf-8 -*-
"""Graph Level Predictions on ADNI Data with Hierarchical Clustering

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1TCRNimtb2c9_90nSEAEa2G-37OKVOAm7

#Overview
Protein co-expression graphs have traditionally been utilized to identify novel biomarkers and illuminate biological mechanisms in Alzheimer's disease (AD). In this project, we aim to use a GNN that predicts disease status based on individuals' proteomic profile. We will be working with cerebrospinal fluid (CSF) data from the Alzheimer's Disease Neuroimaging Initiative (ADNI). This data contains expression data for roughly 85 proteins, collected from 310 subjects total. We chose this dataset because ADNI is one of the largest, longitudinal studies of AD in humans; it not only contains rich, phenotypic data from subjects (clinical information, neuroimaging, biomarkers, cognition, and genetic profile), it also has one of the most open data access policies.

This code will carrying out the task of AD prediction from protein expression data. From the ADNI data, we will construct an adjacency matrix (based on the biweight mid-correlations between node pairs), representing the similarity between different proteins across all subjects. Protein expression levels will provide node information, and each patient will be represented by a graph. 

From here, we will make graph level predictions by learning hierarchically, initially with two levels of pooling. We will use GCN to to generate embeddings reflecting local graph structures followed by clustering based on the ASAPool method. Embeddings will be generated again on the soft clusterings, which we hope will reflect structural , followed by another clustering round before a final graph level prediction.
"""

# Install torch geometric
import os
import torch
print("PyTorch has version {}".format(torch.__version__))
import pandas as pd
import torch.nn.functional as F
import torch_sparse

# The PyG built-in GCNConv
from torch_geometric.nn import GCNConv

import torch_geometric.transforms as T
import numpy
import networkx as nx
import csv
import torch_geometric.utils
from torch_geometric.data import Data
from torch_geometric.data import DataLoader
from tqdm.notebook import tqdm





"""#Load Datasets"""

url1 = 'https://raw.githubusercontent.com/sdos1/cs224w_adni_files/main/protein_adjacency_matrix.csv'
df1 = pd.read_csv(url1)
# Protein Co-Expression Dataset is now stored in a Pandas Dataframe
df1.to_csv('protein_adjacency_matrix.csv')

url2 = 'https://raw.githubusercontent.com/sdos1/cs224w_adni_files/main/final_diagnosis.csv'
df2 = pd.read_csv(url2)
# Diagnosis Dataset is now stored in a Pandas Dataframe
df2.to_csv('final_diagnosis.csv')

url3 = 'https://raw.githubusercontent.com/sdos1/cs224w_adni_files/main/log_transformed_ADNI_expression_data_with_covariates.csv'
df3 = pd.read_csv(url3)
# Patient Expression Dataset is now stored in a Pandas Dataframe
df3.to_csv('log_transformed_ADNI_expression_data_with_covariates.csv')

"""# Import graph and patient level data

"""



## Save the values into an adjacency matrix
adj = numpy.loadtxt(open("protein_adjacency_matrix.csv", "rb"), delimiter=",", skiprows=1, usecols=numpy.arange(2, 53))


#Set up graph from adjacency matrix and assign protein name labels
#changed G = nx.from_numpy_matrix to nx.from_numpy_array
#i had to install pip install ipywidgets

G = nx.from_numpy_array(adj, parallel_edges=False, create_using=None)

print(G)
nx.draw(G, with_labels=True)

## Save the protein expression levels into a matrix
expression_mat = numpy.loadtxt(open("log_transformed_ADNI_expression_data_with_covariates.csv", "rb"), delimiter=",", skiprows=1, usecols=numpy.arange(16, 67))
# print(expression_mat[50,:])

## Save the diagnosis into a dict matching the label number
with open("final_diagnosis.csv") as file_name:
  file_read = csv.reader(file_name)
  diagnosis_list = list(file_read)
## Convert the diagnosis information into a binary classification (1 if AD)
binary_diagnosis = []
for i in range(len(diagnosis_list)):
  if i>0:
    if diagnosis_list[i][1] == "AD":
      binary_diagnosis.append(1)
    else:
      binary_diagnosis.append(0)

"""# Pre-process Data for PyTorch

The high level goal is to create and load a set of graphs (split into test, training and validation sets) that represent the protein expression levels for different protein nodes for each individual. They will use the same common graph adjacency matrix. We also include a random positional encoder based on a shallow encoding which is the same across all graphs. 

"""




x_tensor = torch.from_numpy(expression_mat).float()
diagnosis_tensor = torch.Tensor(binary_diagnosis).long()
adj_tensor = torch.from_numpy(adj)
G_convert = torch_geometric.utils.from_networkx(G)

positional_encoder = torch.rand(51,3).float()

split_idx = {}
split_idx['train'] = torch.tensor(numpy.arange(0, 149))
split_idx['valid'] = torch.tensor(numpy.arange(150, 299))
split_idx['test'] = torch.tensor(numpy.arange(300, 449))

train_list = []
test_list = []
valid_list = []
for i in range(len(diagnosis_tensor)):
  x_yeet = x_tensor[i,:]
  x_scalar = torch.t(torch.reshape(x_yeet, (1, len(x_yeet)))).float()
  x = torch.cat((x_scalar, positional_encoder), 1)
  y = diagnosis_tensor[i]
  if (i in split_idx['train']):
    train_list.append(Data(x=(x), y = y, edge_index=G_convert.edge_index, edge_attr = G_convert.weight))
    # print(train_list[i])
  if (i in split_idx['valid']):
    valid_list.append(Data(x=(x), y = y, edge_index=G_convert.edge_index, edge_attr = G_convert.weight))
  if (i in split_idx['test']):
    test_list.append(Data(x=(x), y = y, edge_index=G_convert.edge_index, edge_attr = G_convert.weight))

print(train_list)

device = 'cuda' if torch.cuda.is_available() else 'cpu'

# If you use GPU, the device should be cuda
print('Device: {}'.format(device))
  
train_loader = DataLoader(train_list, batch_size=32, shuffle=False, num_workers=0)
valid_loader = DataLoader(valid_list, batch_size=32, shuffle=False, num_workers=0)
test_loader = DataLoader(test_list, batch_size=32, shuffle=False, num_workers=0)

"""# GCN Model (Base)

"""

# Set up model arguments
args = {
    'device': device,
    'num_layers': 5,
    'hidden_dim': 256,
    'dropout': 0.5,
    'lr': 0.001,
    'epochs': 50,
}
args

class GCN(torch.nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim, num_layers,
                 dropout, return_embeds=False):
        # Initialisation of self.convs, 
        # self.bns, and self.softmax.

        super(GCN, self).__init__()

        # A list of GCNConv layers
        self.convs = None

        # A list of 1D batch normalization layers
        self.bns = None

        # The log softmax layer
        self.softmax = None

        ## Note:
        ##  self.convs has num_layers GCNConv layers
        ##  self.bns has num_layers - 1 BatchNorm1d layers
        ##  For more information on GCNConv please refer to the documentation:
        ## https://pytorch-geometric.readthedocs.io/en/latest/modules/nn.html#torch_geometric.nn.conv.GCNConv
        ## For more information on Batch Norm1d please refer to the documentation: 
        ## https://pytorch.org/docs/stable/generated/torch.nn.BatchNorm1d.html

        # Construct all convs
        self.convs = torch.nn.ModuleList()

        # construct all bns
        self.bns = torch.nn.ModuleList()

        #For the first layer, we go from dimensions input -> hidden
        #For middle layers we go from dimensions hidden-> hidden
        #For the end layer we go from hidden-> output

        for l in range(num_layers):
          if l==0: #change input output dims accordingly
            self.convs.append(GCNConv(input_dim, hidden_dim))
          elif l == num_layers-1:
            self.convs.append(GCNConv(hidden_dim, output_dim))
          else:
            self.convs.append(GCNConv(hidden_dim, hidden_dim))
          if l < num_layers-1: 
            self.bns.append(torch.nn.BatchNorm1d(hidden_dim))

        self.last_conv = GCNConv(hidden_dim, output_dim)
        self.log_soft = torch.nn.LogSoftmax()

        # Probability of an element getting zeroed
        self.dropout = dropout

        # Skip classification layer and return node embeddings
        self.return_embeds = return_embeds

    def reset_parameters(self):
        for conv in self.convs:
            conv.reset_parameters()
        for bn in self.bns:
            bn.reset_parameters()

    def forward(self, x, adj_t, edge_weight):
        # This function that takes the feature tensor x and
        # edge_index tensor adj_t, and edge_weight and returns the output tensor.

        out = None

        for l in range(len(self.convs)-1):
          x = self.convs[l](x, adj_t, edge_weight)
          x = self.bns[l](x)
          x = F.relu(x)
          x = F.dropout(x, training=self.training)

        x = self.last_conv(x, adj_t, edge_weight)
        if self.return_embeds is True:
          out = x
        else: 
          out = self.log_soft(x)

        return out

"""# Graph Level Prediction Model (inheriting GCN class)

At a high level, we implement the node classification using our earlier GCN model, followed by pooling using the ASAPool function. This allows us to perform prediction over layers of structure. The high level flow is summarised in the figure below. 

We should note that processing occurs with minibatches. To summarise a description from CS224W Colab2, to parallelize the processing of a mini-batch of graphs, PyG combines the graphs into a single disconnected graph data object (*torch_geometric.data.Batch*). *torch_geometric.data.Batch* inherits from *torch_geometric.data.Data* and contains an additional attribute called `batch`. 

The `batch` attribute is a vector mapping each node to the index of its corresponding graph within the mini-batch:

    batch = [0, ..., 0, 1, ..., n - 2, n - 1, ..., n - 1]

This lets us keep track of which graph each node belongs to.

"""

from ogb.graphproppred.mol_encoder import AtomEncoder
from torch_geometric.nn import global_add_pool, global_mean_pool

### GCN to predict graph property
class GCN_Graph(torch.nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim, num_layers, dropout):
        super(GCN_Graph, self).__init__()

        # Node embedding model, initially input_dim=input_dim, output_dim = hidden_dim
        self.gnn_node = GCN(input_dim, hidden_dim,
            hidden_dim, num_layers, dropout, return_embeds=True)
        # Note that the input_dim and output_dim are set to hidden_dim
        # for subsequent layers
        self.gnn_node_2 = GCN(hidden_dim, hidden_dim,
        hidden_dim, num_layers, dropout, return_embeds=True)

        ##Set up pooling layer using ASAPool
        ## For more information please refere to the documentation:
        ## https://pytorch-geometric.readthedocs.io/en/latest/modules/nn.html#torch_geometric.nn.pool.ASAPooling
        self.asap = torch_geometric.nn.pool.ASAPooling(in_channels = 256, ratio = 0.5, dropout = 0.1, negative_slope = 0.2, add_self_loops = False)

        ## Initialize self.pool as a global mean pooling layer
        ## For more information please refer to the documentation:
        ## https://pytorch-geometric.readthedocs.io/en/latest/modules/nn.html#global-pooling-layers
        self.pool = global_mean_pool

        # Output layer
        self.linear = torch.nn.Linear(hidden_dim, output_dim)

    def reset_parameters(self):
      self.gnn_node.reset_parameters()
      self.linear.reset_parameters()

    def forward(self, batched_data):
        # This function takes as input a 
        # mini-batch of graphs (torch_geometric.data.Batch) and 
        # returns the predicted graph property for each graph. 
        #
        # Since we are predicting graph level properties,
        # the output will be a tensor with dimension equaling
        # the number of graphs in the mini-batch

    
        # Extract important attributes of our mini-batch
        x, edge_index, batch, edge_weight = batched_data.x, batched_data.edge_index, batched_data.batch, batched_data.edge_attr
        embed = x
        out = None

        ## Note:
        ## 1. We construct node embeddings using existing GCN model
        ## 2. We use the ASAPool module for soft clustering into a coarser graph representation. 
        ## For more information please refere to the documentation:
        ## https://pytorch-geometric.readthedocs.io/en/latest/modules/nn.html#torch_geometric.nn.pool.ASAPooling
        ## 3. After two cycles of this, we use the global pooling layer to aggregate features for each individual graph
        ## For more information please refer to the documentation:
        ## https://pytorch-geometric.readthedocs.io/en/latest/modules/nn.html#global-pooling-layers
        ## 4. We use a linear layer to predict each graph's property
        num_graphs = int(len(batch)/51)
        post_GCN_1 = self.gnn_node(embed, edge_index, edge_weight)
        post_pool_1 = self.asap(post_GCN_1, edge_index)
        post_GCN_2 = self.gnn_node_2(post_pool_1[0], post_pool_1[1], post_pool_1[2])
        post_pool_2 = self.asap(post_GCN_2, post_pool_1[1])
        ultimate_gcn = self.gnn_node_2(post_pool_2[0], post_pool_2[1], post_pool_2[2])

        glob_pool = self.pool(ultimate_gcn, post_pool_2[3], num_graphs)  
        out = self.linear(glob_pool)    

        return out

def train(model, device, data_loader, optimizer, loss_fn):
    # This function that trains your model by 
    # using the given optimizer and loss_fn.
    model.train()
    loss = 0


    for step, batch in enumerate(tqdm(data_loader, desc="Iteration")):
      batch = batch.to(device)

      if batch.x.shape[0] == 1 or batch.batch[-1] == 0:
          pass
      else:
        ## ignore nan targets (unlabeled) when computing training loss.
        is_labeled = batch.y == batch.y

        ## We first:
        ## 1. Zero grad the optimizer
        ## 2. Feed the data into the model
        ## 3. Use `is_labeled` mask to filter output and labels
        ## 4. Feed the output and label to the loss_fn

        optimizer.zero_grad()
        out = model(batch)
        loss = loss_fn(out[is_labeled].squeeze(), batch.y[is_labeled].to(torch.float32).squeeze())              
        
        loss.backward()
        optimizer.step()

    return loss.item()

# The evaluation function
def eval(model, device, loader, evaluator, save_model_results=False, save_file=None):
    model.eval()
    y_true = []
    y_pred = []

    for step, batch in enumerate(tqdm(loader, desc="Iteration")):
        batch = batch.to(device)

        if batch.x.shape[0] == 1:
            pass
        else:
            with torch.no_grad():
                pred = model(batch)

            y_true.append(batch.y.view(pred.shape).detach().cpu())
            y_pred.append(pred.detach().cpu())

    y_true = torch.cat(y_true, dim = 0).numpy()
    y_pred = torch.cat(y_pred, dim = 0).numpy()

    input_dict = {"y_true": y_true, "y_pred": y_pred}

    if save_model_results:
        print ("Saving Model Predictions")
        
        # Create a pandas dataframe with a two columns
        # y_pred | y_true
        data = {}
        data['y_pred'] = y_pred.reshape(-1)
        data['y_true'] = y_true.reshape(-1)

        df = pd.DataFrame(data=data)
        # Save to csv
        df.to_csv('ogbg-molhiv_graph_' + save_file + '.csv', sep=',', index=False)

    return evaluator.eval(input_dict)

"""
Set up arguments for GCN_Graph model. Our data has embedding size 4, which is our input dimension, and our output prediction has a dimension of 1. 

We use the ROC AUC evaluation metric from the PygGraphPropPredDataset. """

from ogb.graphproppred import PygGraphPropPredDataset, Evaluator

if 'IS_GRADESCOPE_ENV' not in os.environ:
  model = GCN_Graph(4, args['hidden_dim'],
              1, args['num_layers'],
              args['dropout']).to(device)
  evaluator = Evaluator(name='ogbg-molhiv')

  dataset = PygGraphPropPredDataset(name='ogbg-molhiv')

import copy

if 'IS_GRADESCOPE_ENV' not in os.environ:
  model.reset_parameters()

  optimizer = torch.optim.Adam(model.parameters(), lr=args['lr'])
  loss_fn = torch.nn.BCEWithLogitsLoss()

  best_model = None
  best_valid_acc = 0

  for epoch in range(1, 1 + args["epochs"]):
    print('Training...')
    loss = train(model, device, train_loader, optimizer, loss_fn)

    print('Evaluating...')
    train_result = eval(model, device, train_loader, evaluator)
    val_result = eval(model, device, valid_loader, evaluator)
    test_result = eval(model, device, test_loader, evaluator)

    train_acc, valid_acc, test_acc = train_result[dataset.eval_metric], val_result[dataset.eval_metric], test_result[dataset.eval_metric]
    if valid_acc > best_valid_acc:
        best_valid_acc = valid_acc
        best_model = copy.deepcopy(model)
    print(f'Epoch: {epoch:02d}, '
          f'Loss: {loss:.4f}, '
          f'Train: {100 * train_acc:.2f}%, '
          f'Valid: {100 * valid_acc:.2f}% '
          f'Test: {100 * test_acc:.2f}%')

if 'IS_GRADESCOPE_ENV' not in os.environ:
  train_acc = eval(best_model, device, train_loader, evaluator)[dataset.eval_metric]
  valid_acc = eval(best_model, device, valid_loader, evaluator, save_model_results=True, save_file="valid")[dataset.eval_metric]
  test_acc  = eval(best_model, device, test_loader, evaluator, save_model_results=True, save_file="test")[dataset.eval_metric]

  print(f'Best model: '
      f'Train: {100 * train_acc:.2f}%, '
      f'Valid: {100 * valid_acc:.2f}% '
      f'Test: {100 * test_acc:.2f}%')

"""# Ordinary Least Squares Model
Below we set up a least squares prediction model for a baseline comparison. 
"""

# Commented out IPython magic to ensure Python compatibility.
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from mpl_toolkits.mplot3d import Axes3D
import statsmodels.api as sm
# %matplotlib inline

# Read in data

x_vals = expression_mat
y_vals = np.reshape(binary_diagnosis, (565,1))

x_train = x_vals[0:149,:]
y_train = y_vals[0:149,:]

x_test = x_vals[300:449,:]
y_test = y_vals[300:449,:]

X = np.vstack((class_one, class_two))
m = len(X)
B = np.reshape(np.ones(m), (565,1))

# Add column of ones to account for bias term
X_new = np.concatenate((B,X),axis=1)
X_new_test = np.concatenate((B,x_test),axis=1)

est=sm.OLS(y_train, X_new)
results = est.fit()
parameters = np.reshape(results.params, (52,1))

# Convert numpy objects to tensors
X_torch = torch.from_numpy(X_new)
y_torch = torch.from_numpy(y_train)
params_torch = torch.from_numpy(parameters)
out_train = torch.from_numpy(X_new @ parameters)
out_test = torch.from_numpy(X_new_test @ parameters)

OLS_loss = loss_fn(out_train.squeeze(), y_torch.to(torch.float32).squeeze())
OLS_loss

def accuracy(pred, label):

  accu = 0.0

  ############# Your code here ############       
  
  pred = torch.where(pred > 0, 1, 0)
  accu += (pred == label).sum().item()
  accu = round(accu/pred.numel(), 4)
  
  #########################################

  return accu

# training accuracy
accu = accuracy(out_train, y_torch)
accu

# test accuracy
accu = accuracy(out_test, y_torch)
accu

"""We note that this test accuracy is lower than that of our best model, of ~50%!"""