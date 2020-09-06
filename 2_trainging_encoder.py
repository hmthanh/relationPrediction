import torch

from models import SpKBGATModified, SpKBGATConvOnly
from torch.autograd import Variable
import torch.nn as nn
import numpy as np
from utils import save_model

import random
import time
from create_config import Config

args = Config()
args.load_config()

print("Loading corpus")
device = "gpu" if args.cuda else "cpu"
Corpus_ = torch.load("{output}corpus_{device}.pt".format(output=args.data_folder, device=device))
entity_embeddings = torch.load("{output}entity_embeddings_{device}.pt".format(output=args.data_folder, device=device))
relation_embeddings = torch.load("{output}relation_embeddings_{device}.pt".format(output=args.data_folder, device=device))
node_neighbors_2hop = Corpus_.node_neighbors_2hop

print("Defining model")
model_gat = SpKBGATModified(entity_embeddings, relation_embeddings, args.entity_out_dim, args.entity_out_dim,
                            args.drop_GAT, args.alpha, args.nheads_GAT)

if args.cuda:
    model_gat.cuda()

print("Defining loss")


def batch_gat_loss(gat_loss_func, train_indices, entity_embed, relation_embed):
    len_pos_triples = int(
        train_indices.shape[0] / (int(args.valid_invalid_ratio_gat) + 1))

    pos_triples = train_indices[:len_pos_triples]
    neg_triples = train_indices[len_pos_triples:]

    pos_triples = pos_triples.repeat(int(args.valid_invalid_ratio_gat), 1)

    source_embeds = entity_embed[pos_triples[:, 0]]
    relation_embeds = relation_embed[pos_triples[:, 1]]
    tail_embeds = entity_embed[pos_triples[:, 2]]

    x = source_embeds + relation_embeds - tail_embeds
    pos_norm = torch.norm(x, p=1, dim=1)

    source_embeds = entity_embed[neg_triples[:, 0]]
    relation_embeds = relation_embed[neg_triples[:, 1]]
    tail_embeds = entity_embed[neg_triples[:, 2]]

    x = source_embeds + relation_embeds - tail_embeds
    neg_norm = torch.norm(x, p=1, dim=1)

    y = -torch.ones(int(args.valid_invalid_ratio_gat) * len_pos_triples).cuda()

    gat_loss = gat_loss_func(pos_norm, neg_norm, y)
    return gat_loss

    
optimizer = torch.optim.Adam(
    model_gat.parameters(), lr=args.lr, weight_decay=args.weight_decay_gat)

scheduler = torch.optim.lr_scheduler.StepLR(
    optimizer, step_size=500, gamma=0.5, last_epoch=-1)

gat_loss_func = nn.MarginRankingLoss(margin=args.margin)

current_batch_2hop_indices = torch.tensor([])
if(args.use_2hop):
    current_batch_2hop_indices = Corpus_.get_batch_nhop_neighbors_all(args, Corpus_.unique_entities_train, node_neighbors_2hop)

if args.cuda:
    current_batch_2hop_indices = Variable(torch.LongTensor(current_batch_2hop_indices)).cuda()
else:
    current_batch_2hop_indices = Variable(torch.LongTensor(current_batch_2hop_indices))

epoch_losses = []   # losses of all epochs
print("Number of epochs {}".format(args.epochs_gat))

for epoch in range(args.epochs_gat):
    print("\nepoch-> ", epoch)
    random.shuffle(Corpus_.train_triples)
    Corpus_.train_indices = np.array(
        list(Corpus_.train_triples)).astype(np.int32)

    model_gat.train()  # getting in training mode
    start_time = time.time()
    epoch_loss = []

    if len(Corpus_.train_indices) % args.batch_size_gat == 0:
        num_iters_per_epoch = len(
            Corpus_.train_indices) // args.batch_size_gat
    else:
        num_iters_per_epoch = (
            len(Corpus_.train_indices) // args.batch_size_gat) + 1

    for iters in range(num_iters_per_epoch):
        start_time_iter = time.time()
        train_indices, train_values = Corpus_.get_iteration_batch(iters)

        if args.cuda:
            train_indices = Variable(
                torch.LongTensor(train_indices)).cuda()
            train_values = Variable(torch.FloatTensor(train_values)).cuda()

        else:
            train_indices = Variable(torch.LongTensor(train_indices))
            train_values = Variable(torch.FloatTensor(train_values))

        # forward pass
        entity_embed, relation_embed = model_gat(
            Corpus_, Corpus_.train_adj_matrix, train_indices, current_batch_2hop_indices)

        optimizer.zero_grad()

        loss = batch_gat_loss(gat_loss_func, train_indices, entity_embed, relation_embed)

        loss.backward()
        optimizer.step()

        epoch_loss.append(loss.data.item())

        end_time_iter = time.time()
        print("Iteration-> {0}  , Iteration_time-> {1:.4f} , Iteration_loss {2:.4f}".format(
            iters, end_time_iter - start_time_iter, loss.data.item()))

    scheduler.step()
    print("Epoch {} , average loss {} , epoch_time {}".format(
        epoch, sum(epoch_loss) / len(epoch_loss), time.time() - start_time))
    epoch_losses.append(sum(epoch_loss) / len(epoch_loss))

    if (epoch > args.epochs_gat - 3):
        save_model(model_gat, args.data_folder, epoch, args.output_folder)

print("2. Train Encoder Successfully !")
