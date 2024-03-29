#!/usr/bin/env python

from __future__ import print_function

import sys
import os
import argparse

import numpy as np
import ehtim as eh
import matplotlib.pyplot as plt

stepname='init'

# Function definitions
def pick(obs, req_sites):
    """
    Pick out observations with only certain sites
    """
    tlists   = obs.tlist()
    mask     = [req_sites.issubset(set(tlist['t1']).union(tlist['t2']))
                for tlist in tlists]
    out      = obs.copy()
    if len(tlists[mask]) == 0:
        return []

    out.data = np.concatenate(tlists[mask])
    return out

def multical(obs, sites, master_caltab, n=3, amp0=8.0, gain_tol=0.1, only_amp=True):
    """
    Apply network_cal() multiple times
    """
    sites  = set(sites) # make sure that sites is a set
    common = {'sites':sites,
              'zbl_uvdist_max':10000000.0,
              'show_solution':False,
              'pad_amp':0.0,
              'gain_tol':gain_tol,
              'processes':0,
              'caltable':True}
    # If the specified sites aren't present, skip the calibration
    if not pick(obs,sites):
        return [obs, master_caltab]

    for i in range(n):
        # Self calibrate the amplitudes
        datadir = '{}-{}-amp'.format(stepname, i)
        caltab = eh.self_cal.network_cal(pick(obs,sites), amp0, method='amp',
                                         **common)
        obs = caltab.applycal(obs, interp='nearest', extrapolate=True)
        caltab.save_txt(obs, datadir=datadir)
        obs_cal_avg.save_uvfits(datadir+'/'+args.output)
        if master_caltab == None:
            master_caltab = caltab
        else:
            master_caltab = master_caltab.merge(caltab)

        if only_amp: 
            continue

        # Self calibrate the phases
        datadir = '{}-{}-phase'.format(stepname, i)
        caltab = eh.self_cal.network_cal(pick(obs,sites), amp0, method='phase',
                                         **common)
        obs = caltab.applycal(obs, interp='nearest', extrapolate=True)
        caltab.save_txt(obs, datadir=datadir)
        obs_cal_avg.save_uvfits(datadir+'/'+args.output)
        if master_caltab == None:
            master_caltab = caltab
        else:
            master_caltab = master_caltab.merge(caltab)

    return [obs, master_caltab]

# Tack to experiment number mapper (Unused, just for record)
expt = {'D':3597,
        'B':3598,
        'C':3599,
        'A':3600,
        'E':3601}

# Argument parsing
parser = argparse.ArgumentParser(description="Perform network calibration")
parser.add_argument('input',                                    help="input uvfits file")
parser.add_argument('-c', '--caldir', default=None,             help="caltable directory")
parser.add_argument('-o', '--output', default=None,             help="output file")
parser.add_argument('-P', '--prune',  default=1,    type=int,   help="pruning factor")
parser.add_argument('-z', '--ampzbl', default=7.0,  type=float, help="amplitude at zero-baseline")
parser.add_argument('-t', '--tavg',   default=10.0, type=float, help="averaging time")
parser.add_argument('-p', '--pol',    default="R",              help="polarization")
args = parser.parse_args()

if args.output is None:
    args.output = os.path.basename(args.input[:-13])+args.pol+args.pol+'+netcal.uvfits'
print("Parameters:")
print("    input: ", args.input)
print("    caltab directory:", args.caldir)
print("    output:", args.output)
print("    prune: ", args.prune)
print("    ampzbl:", args.ampzbl)
print("    tavg:  ", args.tavg)
print("    pol:   ", args.pol)

# Load uvfits file
obs = eh.obsdata.load_uvfits(args.input, force_singlepol=args.pol)
print("Flagging the SMA Reference Antenna...")
obs = obs.flag_sites(["SR"])
print("Flagging points with anomalous snr...")
obs = obs.flag_anomalous('snr', robust_nsigma_cut=3.0)

# Optional: A-priori calibrate by applying the caltable
if args.caldir != None:
    print("Loading the a priori calibration table...")
    caltab  = eh.caltable.load_caltable(obs, args.caldir)
    obs_cal = caltab.applycal(obs, interp='nearest', extrapolate=True, force_singlepol=args.pol)
else:
    obs_cal = obs.copy()

# Coherently average the input data with a specified coherence time
obs_cal_avg = obs_cal.avg_coherent(args.tavg)
# Flag for anomalous snr in the averaged data
obs_cal_avg = obs_cal_avg.flag_anomalous('snr', robust_nsigma_cut=3.0)
# Save the averaged data
obs_cal_avg.save_uvfits(os.path.basename(args.input[:-13])+args.pol+args.pol+'+avg.uvfits')

# Speed up testing
if args.prune > 1:
    obs_cal_avg.data = np.concatenate(obs_cal_avg.tlist()[::args.prune])

# Initialize the master caltable
master_caltab = None

# First get the ALMA and APEX calibration right -- allow modest gain_tol
stepname = 'step1'
sites = {'AA','AP'}
[obs_cal_avg, master_caltab] = multical(obs_cal_avg, sites, master_caltab, n=2, amp0=args.ampzbl, gain_tol=0.3)

# Next get the SMA and JCMT calibration right -- allow modest gain_tol
stepname = 'step2'
sites = {'SM','JC'}
[obs_cal_avg, master_caltab] = multical(obs_cal_avg, sites, master_caltab, n=2, amp0=args.ampzbl, gain_tol=0.3)

# Recalibrate all redundant stations
stepname = 'step3'
sites = {'AA','AP','SM','JC'}
[obs_cal_avg, master_caltab] = multical(obs_cal_avg, sites, master_caltab, n=2, amp0=args.ampzbl, gain_tol=0.1)

# Save output
obs_cal_avg.save_uvfits(args.output)
master_caltab.save_txt(obs, datadir=os.path.basename(args.input[:-13]) + '/master_caltab')
