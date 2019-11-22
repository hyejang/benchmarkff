#!/usr/bin/env python

"""
match_minima.py

Match conformers from sets of different optimizations.
Compute relative energies of corresponding conformers to a reference conformer.
Generate plots for relative conformer energies (one plot per mol).

By:      Victoria T. Lim
Version: Nov 18 2019

"""

import os
import sys
import numpy as np
import pickle
import itertools
import copy
import collections
import matplotlib.pyplot as plt
import matplotlib as mpl
import openeye.oechem as oechem

### ------------------- Functions -------------------


def read_mols(infile, mol_slice=None):
    """
    Open a molecule file and return molecules and conformers as OEMols.
    Provide option to slice the mols to return only a chunk from the
    specified indices.

    Parameters
    ----------
    infile : string
        name of input file with molecules
    mol_slice : list
        list of indices from which to slice mols generator for read_mols
        [start, stop, step]

    Returns
    -------
    mols : OEMols

    """
    ifs = oechem.oemolistream()
    ifs.SetConfTest(oechem.OEAbsCanonicalConfTest())
    if not ifs.open(infile):
        raise FileNotFoundError(f"Unable to open {infile} for reading")
    mols = ifs.GetOEMols()

    if mol_slice is not None:
        if len(mol_slice) != 3 or mol_slice[0] >= mol_slice[1] or mol_slice[2] <= 0:
            raise ValueError("Check input to mol_slice. Should have len 3, "
                "start value < stop value, step >= 1.")

        # TODO more efficient. can't itertools bc lost mol info (name, SD) after next()
        # adding copy/deepcopy doesnt work on generator objects
        # also doesn't work to convert generator to list then slice list
        #mols = itertools.islice(mols, mol_slice[0], mol_slice[1], mol_slice[2])
        #mlist = mlist[mol_slice[0]:mol_slice[1]:mol_slice[2]]

        def incrementer(count, mols, step):
            if step == 1:
                count += 1
                return count
            # use step-1 because for loop already increments once
            for j in range(step-1):
                count += 1
                next(mols)
            return count

        mlist = []
        count = 0
        for i, m in enumerate(mols):

            if count >= mol_slice[1]:
                return mlist
            elif count < mol_slice[0]:
                count += 1
                continue
            else:
                # important to append copy else still linked to orig generator
                mlist.append(copy.copy(m))
                try:
                    count = incrementer(count, mols, mol_slice[2])
                except StopIteration:
                    return mlist

        return mlist

    return mols


def get_sd_list(mol, taglabel):
    """
    Get list of specified SD tag for all confs in mol.

    Parameters
    ----------
    mol : OEMol with N conformers
    taglabel : string
        tag from which to extract SD data

    Returns
    -------
    sdlist : list
        N-length list with value from SD tag

    """

    sd_list = []

    for j, conf in enumerate(mol.GetConfs()):
        for x in oechem.OEGetSDDataPairs(conf):
            if taglabel.lower() in x.GetTag().lower():
                sd_list.append(x.GetValue())
                break

    return sd_list

def read_check_input(infile):
    """
    Read input file into an ordered dictionary.

    Parameters
    ----------
    infile : string
        name of input file to match script

    Returns
    -------
    in_dict : OrderedDict
        dictionary from input file, where key is method and value is dictionary
        first entry should be reference method
        in sub-dictionary, keys are 'sdfile' and 'sdtag'

    """

    in_dict = collections.OrderedDict()

    # read input file
    with open(infile) as f:
        for line in f:

            # skip commented lines or empty lines
            if line.startswith('#'):
                continue
            dataline = [x.strip() for x in line.split(',')]
            if dataline == ['']:
                continue

            # store each file's information in dictionary of dictionaries
            in_dict[dataline[0]] = {'sdfile': dataline[1], 'sdtag': dataline[2]}

    # check that each file exists before starting
    while True:
        list1 = []
        for v in in_dict.values():
            list1.append(os.path.isfile(v['sdfile']))

        # if all elements are True then all files exist
        if all(list1):
            return in_dict
        else:
            print(list1)
            raise ValueError("One or more listed files not found")


def compare_two_mols(rmol, qmol, rmsd_cutoff):
    """
    For two identical molecules, with varying conformers,
        make an M by N comparison to match the M minima of
        rmol to the N minima of qmol. Match is declared
        for lowest RMSD between the two conformers and
        if the RMSD is below rmsd_cutoff.

    Parameters
    ----------
    rmol : OEMol
        reference OEChem molecule with all its filtered conformers
    qmol : OEMol
        query OEChem molecule with all its filtered conformers
    rmsd_cutoff : float
        cutoff above which two structures are considered diff conformers

    Returns
    -------
    molIndices : list
        1D list of qmol conformer indices that correspond to rmol confs

    """

    automorph = True   # take into acct symmetry related transformations
    heavyOnly = False  # do consider hydrogen atoms for automorphisms
    overlay = True     # find the lowest possible RMSD

    molIndices = []    # 1D list, stores indices of matched qmol confs wrt rmol

    for ref_conf in rmol.GetConfs():
        print(f">>>> Matching {qmol.GetTitle()} conformers to minima: "
              f"{ref_conf.GetIdx()+1} <<<<")

        # for this ref_conf, calculate/store RMSDs with all qmol's conformers
        thisR_allQ = []
        for que_conf in qmol.GetConfs():
            rms = oechem.OERMSD(ref_conf, que_conf, automorph, heavyOnly, overlay)
            thisR_allQ.append(rms)

        # for this ref_conf, get qmol conformer index of min RMSD if <=cutoff
        lowest_rmsd_index = [i for i, j in enumerate(thisR_allQ) if j == min(thisR_allQ)][0]
        if thisR_allQ[lowest_rmsd_index] <= rmsd_cutoff:
            molIndices.append(lowest_rmsd_index)
        else:
            print('no match bc rmsd is ', thisR_allQ[lowest_rmsd_index])
            molIndices.append(None)

    return molIndices


def plot_mol_minima(mol_name, minimaE, legend, selected=None, stag=False):
    """
    Generate line plot of conformer energies of all methods (single molecule).

    Parameters
    ----------
    mol_name : string
        title of the mol being plotted
    minimaE : list of lists
        minimaE[i][j] represents ith method and jth conformer energy
    legend : list
        list of strings with all method names in same order as minimaE
    selected : list
        list of indices for methods to be plotted; e.g., [0], [0, 4]
    stag : Boolean
        True to stagger plots to see line trends (in case they all overlap);
        works best with few (<4?) different methods;
        be wary of using this option when comparing energy distributions

    """

    # get details of reference method
    ref_nconfs = len(minimaE[0])
    ref_file = legend[0]
    num_files = len(minimaE)

    # flatten the 2D list into 1D to find min and max for plot
    flatten = [item for sublist in minimaE for item in sublist]
    floor = min(flatten)
    ceiling = max(flatten)

    # stagger each of the methods for ease of viewing
    if stag == True:
        tempMinimaE = []
        for i, file_ene in enumerate(minimaE):
            tempMinimaE.append([x + i / 2. for x in file_ene])
        minimaE = tempMinimaE
        ceiling = ceiling + num_files

    # set figure-related labels
    plttitle = "Relative Energies of %s Minima" % (mol_name)
    plttitle += "\nby Reference: %s" % (ref_file)
    ylabel = "Relative energy (kcal/mol)"
    figname = "minimaE_%s.png" % (mol_name)

    # set xtick labels by either letters or numbers
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    rpt = int((len(minimaE[0]) / 26) + 1)
    xlabs = [''.join(i)
             for i in itertools.product(letters, repeat=rpt)][:ref_nconfs]
    # xticks by numbers instead
    #xlabs = range(len(minimaE[0]))

    # create figure
    fig = plt.figure(figsize=(20, 10))
    ax = fig.gca()
    ax.set_xticks(np.arange(-1, ref_nconfs + 1, 2))

    # label figure; label xticks before plotting for better spacing.
    plt.title(plttitle, fontsize=16)
    plt.ylabel(ylabel, fontsize=20)
    plt.xlabel("conformer minimum", fontsize=20)
    plt.xticks(list(range(ref_nconfs)), xlabs, fontsize=18)
    plt.yticks(fontsize=18)

    # define line colors and markers
    colors = mpl.cm.rainbow(np.linspace(0, 1, num_files))
    markers = [
        "x", "^", "8", "d", "o", "s", "*", "p", "v", "<", "D", "+", ">", "."
    ] * 10

    # plot the data
    for i, file_ene in enumerate(minimaE):

        # skip the non-selected ones if defined
        if selected is not None and i not in selected:
            continue

        # define x's from integer range with step 1
        xi = list(range(ref_nconfs))

        # generate plot
        plt.plot(xi, file_ene, color=colors[i], label=legend[i],
            marker=markers[i], markersize=9)

    # add legend, set plot limits, add grid
    plt.legend(bbox_to_anchor=(0.96, 1), loc=2, prop={'size': 18})
    plt.xlim(-1, ref_nconfs + 1)
    ax.set_yticks(
        np.arange(int(round(floor)) - 2,
                  int(round(ceiling)) + 2))
    plt.grid()

    # save and close figure
    plt.savefig(figname, bbox_inches='tight')
    #plt.show()
    fig.clear()
    plt.close(fig)


def match_minima(in_dict, rmsd_cutoff):
    """
    For different methods, match the conformer minima to those of the reference
        method. Ex. Conf G of reference method matches with conf R of method 2.

    Parameters
    ----------
    in_dict : OrderedDict
        dictionary from input file, where key is method and value is dictionary
        first entry should be reference method
        in sub-dictionary, keys are 'sdfile' and 'sdtag'
    rmsd_cutoff : float
        cutoff above which two structures are considered diff conformers

    Returns
    -------
    mol_dict : dict of dicts
        mol_dict['mol_name']['energies']
        = [[file1: conf1 conf2] [file2: conf1 conf2]]

    """

    # nested dictionary: 1st layer of mol names, 2nd layer of method energies
    mol_dict = {}

    # get first filename representing the reference geometries
    sdf_ref = list(in_dict.values())[0]['sdfile']

    # assess each file against reference
    for ff_label, ff_dict in in_dict.items():
        sdf_query = ff_dict['sdfile']
        sdf_tag = ff_dict['sdtag']

        # load molecules from open reference and query files
        print("\n\nOpening reference file %s" % sdf_ref)
        mols_ref = read_mols(sdf_ref)

        print("Opening query file %s for [ %s ] energies" % (sdf_query, ff_label))
        mols_query = read_mols(sdf_query)

        # loop over each molecule in reference and query files
        for rmol in mols_ref:
            mol_name = rmol.GetTitle()
            ref_nconfs = rmol.NumConfs()
            run_match = False

            for qmol in mols_query:

                # same mol titles should mean same molecular identity;
                # when same molecular identity found, break out of loop to
                # start matching conformers
                if rmol.GetTitle() == qmol.GetTitle():
                    run_match = True
                    break

            # create entry for this mol in mol_dict if not already present
            # energies [i][j] will be 2d list of ith file and jth conformer
            if mol_name not in mol_dict:
                mol_dict[mol_name] = {}
                mol_dict[mol_name] = {'energies': [], 'indices': [], 'ref_nconfs': []}

            # no same molecules were found bt ref and query files
            # for N reference minima of each mol, P matching indices for each ref minimia
            if not run_match:
                print(f"No {mol_name} molecule found in {sdf_query}")

                # fill in -2 error values for conformer indices
                mol_dict[mol_name]['indices'].append([-2] * ref_nconfs)

                # fill in nan values for conformer energies and ref_nconfs
                mol_dict[mol_name]['energies'].append([np.nan] * ref_nconfs)
                mol_dict[mol_name]['ref_nconfs'].append(ref_nconfs)

                # reset mols_query generator
                mols_query = read_mols(sdf_query)

                # continue with the next rmol
                continue

            # store sd data from tags into dictionary
            mol_dict[mol_name]['energies'].append(list(map(float,
                                get_sd_list(qmol, sdf_tag))))

            # actually don't run match if query file is same as reference file
            # keep this section after sd tag extraction of energies
            if sdf_query == sdf_ref:
                print("\nSkipping comparison against self.")
                mol_dict[mol_name]['indices'].append([-1] * ref_nconfs)
                continue

            # run the match here
            # get indices of qmol conformers that match rmol conformers
            molIndices = compare_two_mols(rmol, qmol, rmsd_cutoff)
            mol_dict[mol_name]['indices'].append(molIndices)

    return mol_dict


def calc_rms_error(rel_energies, lowest_conf_indices):
    """
    From relative energies with respect to some conformer from calc_rel_ene,
       calculate the root mean square error with respect to the relative
       conformer energies of the first (reference) file.

    Parameters
    ----------
    rel_energies : 3D list
        energies, where rel_energies[i][j][k] represents ith mol, jth file,
        kth conformer rel energy
    lowest_conf_indices : 1D list
        indices of the lowest energy conformer per each mol

    Returns
    -------
    rms_array : 2D list
        RMS errors for each file with reference to first input file
        rms_array[i][j] represents ith mol, jth file's RMSE

    """
    rms_array = []

    # iterate over each molecule
    for i, mol_array in enumerate(rel_energies):
        mol_rmses = []

        # iterate over each file (FF)
        for j, filelist in enumerate(mol_array):

            # subtract query file minus reference file
            errs = np.asarray(filelist) - np.asarray(mol_array[0])

            # square
            sqrs = errs**2.

            # delete reference conformer since it has zero relative energy
            sqrs = np.delete(sqrs, lowest_conf_indices[i])

            # also delete any nan values (TODO: treat this differently?)
            sqrs = sqrs[~np.isnan(sqrs)]

            # mean, root, store
            mse = np.mean(sqrs)
            rmse = np.sqrt(mse)
            mol_rmses.append(rmse)

        rms_array.append(mol_rmses)

    return rms_array


def calc_rel_ene(matched_enes):
    """
    Calculate conformer relative energies of matching conformers.
        For each file, subtract minimum conformer energy from all conformers.
        The minimum-energy conformer minimum is chosen from first
        finding the method with the least number of missing energies,
        then of that method, choosing the lowest energy conformer.
    For mols with a single conformer it doesn't make sense to calculate
        relative energies. These mols are removed from matched_enes.

    Parameters
    ----------
    matched_enes : 3D list
        energies, matched_enes[i][j][k] represents energy of
        ith mol, jth file, kth conformer

    Returns
    -------
    rel_energies : 3D list
        energies in same format as above except with relative energies
    lowest_conf_indices : 1D list
        indices of the lowest energy conformer by reference mols

    """

    lowest_conf_indices = []

    # loop over molecules
    for i, mol_array in enumerate(matched_enes):

        # get number of conformers in reference file
        ref_nconfs = len(mol_array[0])

        # for this mol, count number of conf nans for each method (1d list)
        nan_cnt = []
        for j in range(ref_nconfs):
            nan_cnt.append(sum(np.isnan([file_enes[j] for file_enes in mol_array])))
        #print("mol {} nan_cnt: {}".format(i, nan_cnt))

        # find which method has fewest nans; equiv to finding which query
        # method has most number of conformer matches

        # no_nan_conf_inds: list of conf indices with no nans across all files
        no_nan_conf_inds = np.empty(0)
        cnt = 0

        # check which confs have 0 method nans. if none of them, check which
        # have 1 nan across all files, etc. repeat until you find the smallest
        # nan value for which you get conformer indices with that number nans.
        # leave loop when 'no_nan_conf_inds' is assigned or if nothing left in nan_cnt
        while no_nan_conf_inds.size == 0 and cnt < ref_nconfs:
            no_nan_conf_inds = np.where(np.asarray(nan_cnt) == cnt)[0]
            cnt += 1

        # for an existing no_nan_conf_inds, get lowest energy conf of reference method
        if no_nan_conf_inds.size > 0:

            # get energies from reference [0] file
            leastNanEs = np.take(mol_array[0], no_nan_conf_inds)

            # find index of the lowest energy conformer
            lowest_conf_idx = no_nan_conf_inds[np.argmin(leastNanEs)]
            lowest_conf_indices.append(lowest_conf_idx)

        # if no_nan_conf_inds not assigned, this means all methods had all nans
        # in this case just get index of conformer with lowest number of nans
        else:
            lowest_conf_indices.append(nan_cnt.index(min(nan_cnt)))

    # after going thru all mols, calc relative energies by subtracting lowest
    rel_energies = []
    for z, molE in zip(lowest_conf_indices, matched_enes):

        # temp list for this mol's relative energies
        temp = []

        # subtract energy of lowest_conf_index; store in list
        for fileE in molE:
            temp.append(
                [(fileE[i] - fileE[z]) for i in range(len(fileE))])
        rel_energies.append(temp)

    return rel_energies, lowest_conf_indices


def write_rel_ene(mol_name, rmse, relEnes, low_ind, ff_list, prefix='relene'):
    """
    Write the relative energies and RMSEs in an output text file.

    Parameters
    ----------
    mol_name : string
        title of the mol being written out
    rmse : list
        1D list of RMSEs for all the compared methods against ref method
    relEnes : 2D list
        relEnes[i][j] represents energy of ith method and jth conformer
    low_ind : int
        integer of the index of the lowest energy conformer
    ff_list : list
        list of methods including reference as the first
    prefix : string
        prefix of output dat file

    """

    ofile = open(f"{prefix}_{mol_name}.dat", 'w')
    ofile.write(f"# Molecule %s\n" % mol_name)
    ofile.write("# Energies (kcal/mol) for conformers matched to first method.")
    ofile.write(f"\n# Energies are relative to conformer {low_ind}.\n")
    ofile.write("# Rows represent conformers; columns represent methods.\n")

    # write methods, RMSEs, integer column header
    rmsheader = "\n# "
    colheader = "\n\n# "
    for i, method in enumerate(ff_list):
        ofile.write(f"\n# {i+1} {method}")
        rmsheader += f"\t{rmse[i]:.4f}"
        colheader += f"\t\t{i+1}"

    ofile.write("\n\n# RMS errors by method, with respect to the " +
                "first method listed:")
    ofile.write(rmsheader)
    ofile.write(colheader)

    # write each ff's relative energies
    for i in range(len(relEnes[0])):

        # label conformer row
        ofile.write(f"\n{i}\t")

        # write energies for this conformer of all methods
        thisline = [x[i] for x in relEnes]
        thisline = ['%.4f' % elem for elem in thisline]
        thisline = '\t'.join(map(str, thisline))
        ofile.write(thisline)

    ofile.close()


def extract_matches(mol_dict):
    """
    This function checks if minima is matched, using indices lists inside dict.
    If match is found, store the corresponding energy under a new key with
    value of "energies_matched". If there is no match, the energy listed in the
    dict is not used; rather, nan is added as placeholder.

    Parameter
    ---------
    mol_dict : dict of dicts
        mol_dict['mol_name']['energies']
        = [[file1: conf1 conf2] [file2: conf1 conf2]]

    Returns
    -------
    mol_dict : dict of dicts
        mol_dict['mol_name']['energies']
        mol_dict['mol_name']['energies_matched']

    """

    # iterate over each molecule
    for m in mol_dict:

        # 2D list, [i][j] i=filename (FF), j=index
        # index represents queried mol's conformation location that matches
        # the ref mol's conformer
        queried_indices = mol_dict[m]['indices']

        # 2D list, [i][j] i=filename (FF), j=energy
        energy_array = mol_dict[m]['energies']

        # based on the indices, extract the matching energies
        updated = []

        for i, file_indices in enumerate(queried_indices):
            fileData = []

            for j, conf_index in enumerate(file_indices):

                # conformers were matched but all RMSDs were beyond cutoff
                # as set in the compare_two_mols function
                if conf_index is None:
                    print(
                        "No matching conformer within RMSD cutoff for {}th "
                        "conf of {} mol in {}th file.".format(j, m, i))
                    fileData.append(np.nan)

                # the query molecule was missing
                elif conf_index == -2:
                    # only print this warning message once per mol
                    if j == 0:
                        print("!!!! The entire {} mol is not found in "
                              "{}th file. !!!!".format(m, i))
                    fileData.append(np.nan)

                # energies are missing somehow?
                elif len(energy_array[i]) == 0:
                    print("!!!! Mol {} was found and confs were matched by "
                          "RMSD but there are no energies of {}th method. !!!!".format(m, i))
                    fileData.append(np.nan)

                # conformers not matched bc query file = reference file
                # reference indices therefore equals query indices
                elif conf_index == -1:
                    fileData.append(float(energy_array[i][j]))

                # conformers matched and there exists match within cutoff
                else:
                    fileData.append(float(energy_array[i][conf_index]))

            updated.append(fileData)

        mol_dict[m]['energies_matched'] = updated

    return mol_dict


def main(in_dict, readpickle, plot, rmsd_cutoff):
    """
    Execute the minima matching.

    Parameter
    ---------
    in_dict : OrderedDict
        dictionary from input file, where key is method and value is dictionary
        first entry should be reference method
        in sub-dictionary, keys are 'sdfile' and 'sdtag'
    readpickle : Boolean
        read in data from match.pickle
    plot : Boolean
        generate line plots of conformer energies
    rmsd_cutoff : float
        cutoff above which two structures are considered diff conformers

    """

    # run matching, unless reading in from pickle file
    if readpickle:
        mol_dict = pickle.load(open('match.pickle', 'rb'))
    else:
        # match conformers
        mol_dict = match_minima(in_dict, rmsd_cutoff)

        # save results in pickle file
        pickle.dump(mol_dict, open('match.pickle', 'wb'))

    # process dictionary to match the energies by RMSD-matched conformers
    numMols = len(mol_dict)
    mol_dict = extract_matches(mol_dict)

    # collect the matched energies into a list of lists
    matched_enes = []
    for m in mol_dict:
        matched_enes.append(mol_dict[m]['energies_matched'])

    # with matched energies, calculate relative values and RMS error
    rel_energies, lowest_conf_indices = calc_rel_ene(matched_enes)
    rms_array = calc_rms_error(rel_energies, lowest_conf_indices)

    # write out data file of relative energies
    mol_names = mol_dict.keys()
    ff_list = list(in_dict.keys())

    for i, mn in enumerate(mol_names):
        write_rel_ene(mn, rms_array[i], rel_energies[i], lowest_conf_indices[i], ff_list)

    if plot:
        for i, m in enumerate(mol_dict):

            # only plot for single molecule
             #if m != 'AlkEthOH_c1178': continue

            plot_mol_minima(m, rel_energies[i], ff_list)

            # only plot selected methods
            #plot_mol_minima(m, rel_energies[i], ff_list, selected=[0])


### ------------------- Parser -------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument("-i", "--infile",
        help="Name of text file with force field in first column and molecule "
             "file in second column. Columns separated by commas.")

    parser.add_argument("--readpickle", action="store_true", default=False,
        help="Read in data from pickle files named \"match.pickle\" from each "
             "force field's directory.")

    parser.add_argument("--plot", action="store_true", default=False,
        help="Generate line plots for every molecule with the conformer "
             "relative energies.")

    parser.add_argument("--cutoff", type=float, default=0.5,
        help="RMSD cutoff above which conformers are considered different "
             "enough to be distinct. Corresponding energies not considered. "
             "Measured by OpenEye in with automorph=True, heavyOnly=False, "
             "overlay=True. Units in Angstroms.")


    # parse arguments
    args = parser.parse_args()
    if not os.path.exists(args.infile):
        parser.error(f"Input file {args.infile} does not exist.")

    # read main input file and check that files within exist
    in_dict = read_check_input(args.infile)

    # run match_minima
    main(in_dict, args.readpickle, args.plot, args.cutoff)

