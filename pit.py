# -*- coding: utf-8 -*-
"""
Created on Tue Nov 24 14:16:50 2020

@author: MatteoRisso
"""

import numpy as np
import tensorflow as tf
import argparse
import json
import config as cf
import sys

import math

# Limit GPU usage
if cf.machine == 'server':
    if tf.__version__ == '1.14.0':
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.2)
        sess = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options))
        # some aliases necessary in tf 1.14
        val_mae = 'val_mean_absolute_error'
        mae = 'mean_absolute_error'
    else:
        limit = 1024 * 4
        gpus = tf.config.experimental.list_physical_devices('GPU')
        if gpus:
            try:
                tf.config.experimental.set_virtual_device_configuration(gpus[0], [tf.config.experimental.VirtualDeviceConfiguration(memory_limit=limit)])
            except RuntimeError as e:
                print(e)
        # some aliases necessary in tf > 1.14
        val_mae = 'val_mae'
        mae = 'mae'

if tf.__version__ == '1.14.0':
    # some aliases necessary in tf 1.14
    val_mae = 'val_mean_absolute_error'
    mae = 'mean_absolute_error'
else:
    # some aliases necessary in tf > 1.14
    val_mae = 'val_mean_absolute_error'
    mae = 'mean_absolute_error'

from tensorflow.keras.optimizers import Adam, SGD
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

from sklearn.model_selection import LeaveOneGroupOut, GroupKFold
from sklearn.utils import shuffle

from scipy.io import loadmat

from custom_callbacks import SaveGamma, export_structure

import preprocessing as pp

import train_TEMPONet
import train_ResTCN

import build_TEMPONet
import build_ResTCN

from preprocessing_WordPTB import data_generator, batchify, get_batch
from preprocessing_CharPTB import data_generator as data_generator_c 
from preprocessing_CharPTB import batchify as batchify_c 
from preprocessing_CharPTB import get_batch as get_batch_c
from preprocessing_CharPTB import char_tensor


import utils

from custom_losses import NLL, accuracy

# PARSER
parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('dataset', help='PPG_Dalia | Nottingham | to be completed...')
parser.add_argument('strength', help='Regularization Strength')
parser.add_argument('warmup', help='Number of warmup epochs')
args = parser.parse_args()

# Setup config
cf.dataset = args.dataset
cf.reg_strength = float(args.strength)
try:
    cf.warmup = int(args.warmup)
except:
    cf.warmup = args.warmup

# Common callbacks
save_gamma = SaveGamma()
exp_str = export_structure()

# PPG_Dalia
if args.dataset == 'PPG_Dalia':
    
    if cf.original_ofmap:
        ofmap = []
    else:
        ofmap = [
                7, 21, 1,
                64, 1, 34,
                9, 7, 5,
                4, 36, 1
                ]

    early_stop = EarlyStopping(monitor=val_mae, min_delta=0.01, patience=35, mode='min', verbose=1)
    
    # Load data
    X, y, groups, activity = pp.preprocessing(cf.dataset)

    # organize data
    group_kfold = GroupKFold(n_splits=4)
    group_kfold.get_n_splits(X, y, groups)
    
    # Learn dil fact
    model = build_TEMPONet.TEMPONet_d1(1, cf.input_shape, ofmap=ofmap)
    del model
    model = build_TEMPONet.TEMPONet_d1(1, cf.input_shape, trainable=False,
            ofmap=ofmap)
    

    # save model and weights
    checkpoint = ModelCheckpoint(cf.saving_path+'autodil/trained_weights_warmup'+str(cf.warmup)+'.h5', 
                                 monitor=val_mae, verbose=1, 
                                 save_best_only=True, save_weights_only=True, mode='min', period=1)
    #configure  model
    adam = Adam(lr=cf.lr, beta_1=0.9, beta_2=0.999, epsilon=1e-08)
    model.compile(loss='logcosh', optimizer=adam, metrics=[mae])

    X_sh, y_sh = shuffle(X, y)
    #import pdb
    #pdb.set_trace()
    # Warmup
    if cf.warmup != 0:
        print('Train model for {} epochs'.format(cf.warmup))
        strg = cf.reg_strength
        cf.reg_strength = 0

        if cf.warmup == 'max':
            epochs_num = cf.epochs
        else:
            epochs_num = cf.warmup

        train_TEMPONet.warmup(model, epochs_num, X_sh, y_sh, early_stop, checkpoint)
        #hist = model.fit(x=np.transpose(X_sh.reshape(X_sh.shape[0], 4, cf.input_shape, 1),                         (0, 3, 2, 1)), \
        #                  y=y_sh, shuffle=True, \
        #                  validation_split=0.1, verbose=1, \
        #                  batch_size= cf.batch_size, epochs=epochs_num,
        #                  callbacks = [early_stop, checkpoint])
        cf.reg_strength = strg
    
    del model

    model = build_TEMPONet.TEMPONet_d1(1, cf.input_shape, trainable=True,
            ofmap=ofmap)
    model.compile(loss='logcosh', optimizer=adam, metrics=[mae])

    if cf.warmup != 0:
        tmp_model = build_TEMPONet.TEMPONet_d1(1, cf.input_shape, trainable=False, ofmap=ofmap)
        # load weights in temp model
        tmp_model.load_weights(cf.saving_path+'autodil/trained_weights_warmup'+str(cf.warmup)+'.h5')
        
        utils.copy_weights(model, tmp_model)

    # Train gammas
    print('Train on Gammas')
    print('Reg strength : {}'.format(cf.reg_strength))

    train_TEMPONet.train_gammas(model, X_sh, y_sh, early_stop, save_gamma, exp_str)
    
    # Retrain and cross-validate
    tr_model, MAE = train_TEMPONet.retrain(groups, X, y, activity, checkpoint, early_stop, ofmap)
    
    print(MAE)
    # Evaluate average MAE
    avg = 0
    for _, val in MAE.items():
        avg += val
        print("Average MAE : %f", avg/len(MAE))

    # summary file
    f=open("summary_PPG_Dalia_warmup{}.txt".format(cf.warmup), "a+")

    f.write("regularization strength : {reg_str} \t threshold : {th} \t MAE : {mae} \t Model size : {size} \n".format(
           reg_str = cf.reg_strength,
           th = cf.threshold,
           mae = avg/len(MAE),
           size = tr_model.count_params()))

    f.close()

# Nottingham and JSB_Chorales
elif args.dataset == 'Nottingham' or args.dataset == 'JSB_Chorales':
    early_stop = EarlyStopping(monitor='val_loss', min_delta=0.01, patience=35, mode='min', verbose=1)

    # Load data
    if args.dataset == 'Nottingham':
        data = loadmat(cf.path_Nottingham)
    elif args.dataset == 'JSB_Chorales':
        data = loadmat(cf.path_JSB_Chorales)

    X_train = data['traindata'][0]
    X_valid = data['validdata'][0]
    X_test = data['testdata'][0]

    # build model
    model = build_ResTCN.ResTCN_d1(cf.n_classes, cf.n_channels, cf.k, cf.dp, variant=args.dataset)
    del model
    model = build_ResTCN.ResTCN_d1(cf.n_classes, cf.n_channels, cf.k, cf.dp, 
                                   trainable=False, variant=args.dataset)

    opt = Adam(lr=cf.lr, clipvalue=0.4)
    model.compile(
             loss=NLL,
             optimizer=opt)

    if cf.warmup != 0:
        print('Train model for {} epochs'.format(cf.warmup))
        strg = cf.reg_strength
        cf.reg_strength = 0

        if cf.warmup == 'max':
            epochs_num = cf.epochs
        else:
            epochs_num = cf.warmup

        train_ResTCN.warmup_Nottingham(model, epochs_num, X_train, X_valid, X_test)
        cf.reg_strength = strg

    del model
    # build new model with trainable gamma
    model = build_ResTCN.ResTCN_d1(cf.n_classes, cf.n_channels, cf.k, cf.dp,
                                   trainable=True, variant=args.dataset)
    model.compile(
           loss=NLL,
           optimizer=opt)
    
    if cf.warmup != 0:
        tmp_model = build_ResTCN.ResTCN_d1(cf.n_classes, cf.n_channels, cf.k, cf.dp, 
                                           trainable=False, variant=args.dataset)
        # load weights in temp model
        tmp_model.load_weights(cf.saving_path+'autodil/trained_weights_warmup'+str(cf.warmup)+'.h5')
        utils.copy_weights(model, tmp_model)

    # train on gammas
    print('Train on Gammas')
    print('Reg strength : {}'.format(cf.reg_strength))

    train_ResTCN.train_gammas_Nottingham(model, cf.epochs, X_train, X_valid, X_test)

    # retrain
    # obtain conv #output filters from learned json structure
    with open(cf.saving_path+'autodil/learned_dil_'+'{:.1e}'.format(cf.reg_strength)+'_'+'{:.1e}'.format(cf.threshold)+'_{}'.format(cf.warmup)+'.json', 'r') as f:
        dil_list = [val for _,val in json.loads(f.read()).items()]

    del model
    model = build_ResTCN.ResTCN_learned(cf.n_classes, cf.n_channels, cf.k,cf.dp, 
                                        dil_list=dil_list, variant=args.dataset)

    model.compile(
           loss=NLL,
           optimizer=opt)
    best_t_l = train_ResTCN.retrain_Nottingham(model, cf.epochs, X_train, X_valid, X_test)
    
    # summary file
    f=open("summary_"+args.dataset+"_warmup{}.txt".format(cf.warmup), "a+")

    f.write("regularization strength : {reg_str} \t threshold : {th} \t Loss : {loss} \t Model size : {size} \n".format(
                       reg_str = cf.reg_strength,
                       th = cf.threshold,
                       loss = best_t_l,
                       size = model.count_params()))

    f.close()

# SeqMNIST and PerMNIST
elif args.dataset == 'SeqMNIST' or args.dataset == 'PerMNIST':
    early_stop = EarlyStopping(monitor='val_accuracy', min_delta=0.01, patience=35, mode='max', verbose=1)
    
    # Load data
    (X_train, y_train), (X_test, y_test) = tf.keras.datasets.mnist.load_data()
    
    # Normalize
    mean = 0.1307
    std = 0.3081
    X_train = (X_train - mean) / std
    X_test = (X_test - mean) / std
    
    # Serialize
    X_train = X_train.reshape((X_train.shape[0], 1, X_train.shape[1]*X_train.shape[2]))
    X_test = X_test.reshape((X_test.shape[0], 1, X_test.shape[1]*X_test.shape[2]))
    
    if args.dataset == 'PerMNIST':
        perm = np.random.permutation(X_train.shape[-1])
        X_train = X_train[:,:,perm]
        X_test = X_test[:,:,perm]
    
    X_train, y_train = shuffle(X_train, y_train)
    
    # save model and weights
    checkpoint = ModelCheckpoint(cf.saving_path+'autodil/trained_weights_warmup'+str(cf.warmup)+'.h5', 
                                 monitor='val_accuracy', verbose=1, 
                                 save_best_only=True, save_weights_only=True, mode='max', period=1)
    
    # build model
    model = build_ResTCN.ResTCN_d1(cf.n_classes, cf.n_channels, cf.k, cf.dp, variant=args.dataset)
    del model
    model = build_ResTCN.ResTCN_d1(cf.n_classes, cf.n_channels, cf.k, cf.dp, 
                                   trainable=False, variant=args.dataset)
    
    opt = Adam(lr=cf.lr)
    model.compile(
                 loss='sparse_categorical_crossentropy',
                 optimizer=opt,
                 metrics=[accuracy])
    
    if cf.warmup != 0:
        print('Train model for {} epochs'.format(cf.warmup))
        strg = cf.reg_strength
        cf.reg_strength = 0

        if cf.warmup == 'max':
            epochs_num = cf.epochs
        else:
            epochs_num = cf.warmup

        train_ResTCN.warmup_SeqMNIST(model, epochs_num, X_train, y_train, early_stop, checkpoint)
        cf.reg_strength = strg
    
    del model
    # build new model with trainable gamma
    model = build_ResTCN.ResTCN_d1(cf.n_classes, cf.n_channels, cf.k, cf.dp,
                                   trainable=True, variant=args.dataset)
    model.compile(
            loss='sparse_categorical_crossentropy',
            optimizer=opt,
            metrics=[accuracy])
    
    if cf.warmup != 0:
        tmp_model = build_ResTCN.ResTCN_d1(cf.n_classes, cf.n_channels, cf.k, cf.dp, 
                                           trainable=False, variant=args.dataset)
        # load weights in temp model
        tmp_model.load_weights(cf.saving_path+'autodil/trained_weights_warmup'+str(cf.warmup)+'.h5')
        utils.copy_weights(model, tmp_model)

    # train on gammas
    print('Train on Gammas')
    print('Reg strength : {}'.format(cf.reg_strength))

    train_ResTCN.train_gammas_SeqMNIST(model, X_train, y_train, early_stop, save_gamma, exp_str)

    # retrain
    # obtain conv #output filters from learned json structure
    with open(cf.saving_path+'autodil/learned_dil_'+'{:.1e}'.format(cf.reg_strength)+'_'+'{:.1e}'.format(cf.threshold)+'_{}'.format(cf.warmup)+'.json', 'r') as f:
        dil_list = [val for _,val in json.loads(f.read()).items()]

    del model
    model = build_ResTCN.ResTCN_learned(cf.n_classes, cf.n_channels, cf.k,cf.dp, 
                                        dil_list=dil_list, variant=args.dataset)

    model.compile(
            loss='sparse_categorical_crossentropy',
            optimizer=opt,
            metrics=[accuracy])
    train_ResTCN.retrain_SeqMNIST(model, cf.epochs, X_train, y_train, X_test, 
                                             y_test, early_stop, checkpoint)
    best_t_l = model.evaluate(
            X_test.reshape(-1, 1, X_test.shape[-1], 1), 
            y_test.reshape(y_test.shape[0], 1))
    # summary file
    f=open("summary_"+args.dataset+"_warmup{}.txt".format(cf.warmup), "a+")

    f.write("regularization strength : {reg_str} \t threshold : {th} \t Acc : {loss} \t Model size : {size} \n".format(
                       reg_str = cf.reg_strength,
                       th = cf.threshold,
                       loss = best_t_l,
                       size = model.count_params()))

    f.close()

# Word_PTB
elif args.dataset == 'Word_PTB':
    early_stop = EarlyStopping(monitor='val_loss', min_delta=0.01, patience=35, mode='min', verbose=1)

    # Load data
    corpus = data_generator('Word_PTB')

    eval_batch_size = 10
    X_train = batchify(corpus.train, cf.batch_size)
    X_valid = batchify(corpus.valid, eval_batch_size)
    X_test = batchify(corpus.test, eval_batch_size)
    
    n_words = len(corpus.dictionary)
    
    n_classes = list()
    n_classes.append(n_words)
    n_classes.append(cf.emb_size)
    
    num_chans = cf.n_channels[:-1] + [cf.emb_size]

    # build model
    model = build_ResTCN.ResTCN_d1(n_classes, num_chans, cf.k, cf.dp, variant=args.dataset)
    del model
    model = build_ResTCN.ResTCN_d1(n_classes, num_chans, cf.k, cf.dp, 
                                   trainable=False, variant=args.dataset,
                                   hyst=cf.hyst)

    opt = Adam(lr=cf.lr, clipnorm=0.4)
    model.compile(
             loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
             optimizer=opt)

    if cf.warmup != 0:
        print('Train model for {} epochs'.format(cf.warmup))
        strg = cf.reg_strength
        cf.reg_strength = 0

        if cf.warmup == 'max':
            epochs_num = cf.epochs
        else:
            epochs_num = cf.warmup

        train_ResTCN.warmup_Word_PTB(model, epochs_num, n_words, X_train, X_valid, X_test)
        cf.reg_strength = strg

    del model
    # build new model with trainable gamma
    model = build_ResTCN.ResTCN_d1(n_classes, num_chans, cf.k, cf.dp,
                                   trainable=True, variant=args.dataset,
                                   hyst=cf.hyst)
    model.compile(
           loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
           optimizer=opt)
    
    if cf.warmup != 0:
        tmp_model = build_ResTCN.ResTCN_d1(n_classes, num_chans, cf.k, cf.dp, 
                                           trainable=False, variant=args.dataset, hyst=cf.hyst)
        # load weights in temp model
        tmp_model.load_weights(cf.saving_path+'autodil/trained_weights_warmup'+str(cf.warmup)+'.h5')
        utils.copy_weights(model, tmp_model)

    # train on gammas
    print('Train on Gammas')
    print('Reg strength : {}'.format(cf.reg_strength))

    train_ResTCN.train_gammas_Word_PTB(model, cf.epochs, n_words, X_train, X_valid, X_test)

    # retrain
    # obtain conv #output filters from learned json structure
    with open(cf.saving_path+'autodil/learned_dil_'+'{:.1e}'.format(cf.reg_strength)+'_'+'{:.1e}'.format(cf.threshold)+'_{}'.format(cf.warmup)+'.json', 'r') as f:
        dil_list = [val for _,val in json.loads(f.read()).items()]

    del model
    model = build_ResTCN.ResTCN_learned(n_classes, num_chans, cf.k,cf.dp, 
                                        dil_list=dil_list, variant=args.dataset)

    model.compile(
           loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
           optimizer=opt)
    best_t_l = train_ResTCN.retrain_Word_PTB(model, cf.epochs, n_words, X_train, X_valid, X_test)
    
    # summary file
    f=open("summary_"+args.dataset+"_warmup{}.txt".format(cf.warmup), "a+")

    f.write("regularization strength : {reg_str} \t threshold : {th} \t Loss : {loss} \t Model size : {size} \n".format(
                       reg_str = cf.reg_strength,
                       th = cf.threshold,
                       loss = math.exp(best_t_l),
                       size = model.count_params()))

    f.close()

# Char_PTB
elif args.dataset == 'Char_PTB':
    early_stop = EarlyStopping(monitor='val_loss', min_delta=0.01, patience=35, mode='min', verbose=1)

    # Load data
    file, file_len, valfile, valfile_len, testfile, testfile_len, corpus = data_generator_c('Char_PTB')

    eval_batch_size = 10
    X_train = batchify_c(char_tensor(corpus, file), cf.batch_size)
    X_valid = batchify_c(char_tensor(corpus, valfile), 1)
    X_test = batchify_c(char_tensor(corpus, testfile), 1)
    
    n_chars = len(corpus.dict)
    
    n_classes = list()
    n_classes.append(n_chars)
    n_classes.append(cf.emb_size)
    
    num_chans = cf.n_channels[:-1] + [cf.emb_size]

    # build model
    model = build_ResTCN.ResTCN_d1(n_classes, num_chans, cf.k, cf.dp, variant=args.dataset)
    del model
    model = build_ResTCN.ResTCN_d1(n_classes, num_chans, cf.k, cf.dp, 
                                   trainable=False, variant=args.dataset)

    #opt = Adam(lr=cf.lr, clipnorm=0.4)
    opt = SGD(learning_rate=cf.lr, clipvalue=0.15)

    if cf.warmup != 0:
        print('Train model for {} epochs'.format(cf.warmup))
        strg = cf.reg_strength
        cf.reg_strength = 0

        if cf.warmup == 'max':
            epochs_num = cf.epochs
        else:
            epochs_num = cf.warmup

        train_ResTCN.warmup_Char_PTB(model, epochs_num, n_chars, X_train, X_valid, X_test)
        cf.reg_strength = strg

    del model
    # build new model with trainable gamma
    model = build_ResTCN.ResTCN_d1(n_classes, num_chans, cf.k, cf.dp,
                                   trainable=True, variant=args.dataset)
    # model.compile(
    #        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
    #        optimizer=opt)
    
    if cf.warmup != 0:
        tmp_model = build_ResTCN.ResTCN_d1(n_classes, num_chans, cf.k, cf.dp, 
                                           trainable=False, variant=args.dataset)
        # load weights in temp model
        tmp_model.load_weights(cf.saving_path+'autodil/trained_weights_warmup'+str(cf.warmup)+'.h5')
        utils.copy_weights(model, tmp_model)

    # train on gammas
    print('Train on Gammas')
    print('Reg strength : {}'.format(cf.reg_strength))

    train_ResTCN.train_gammas_Char_PTB(model, cf.epochs, n_chars, X_train, X_valid, X_test)

    # retrain
    # obtain conv #output filters from learned json structure
    with open(cf.saving_path+'autodil/learned_dil_'+'{:.1e}'.format(cf.reg_strength)+'_'+'{:.1e}'.format(cf.threshold)+'_{}'.format(cf.warmup)+'.json', 'r') as f:
        dil_list = [val for _,val in json.loads(f.read()).items()]

    del model
    model = build_ResTCN.ResTCN_learned(n_classes, num_chans, cf.k,cf.dp, 
                                        dil_list=dil_list, variant=args.dataset)

    # model.compile(
    #        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
    #        optimizer=opt)
    best_t_l = train_ResTCN.retrain_Char_PTB(model, cf.epochs, n_chars, X_train, X_valid, X_test)
    
    # summary file
    f=open("summary_"+args.dataset+"_warmup{}.txt".format(cf.warmup), "a+")

    f.write("regularization strength : {reg_str} \t threshold : {th} \t Loss : {loss} \t Model size : {size} \n".format(
                       reg_str = cf.reg_strength,
                       th = cf.threshold,
                       loss = best_t_l,
                       size = model.count_params()))

    f.close()
    
else:
    print('{} is not supported'.format(args.dataset))
    sys.exit()

