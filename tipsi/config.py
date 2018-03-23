"""config.py contains the class Config, which keeps track of
parameters for the TBPM calculation.

Functions
----------
    create_dir
        Creates directory.

Classes
----------
    Config
        Contains TBPM parameters.
"""

################
# dependencies
################

# numerics & math
import numpy as np
import pickle

# input & output
import h5py
import time
import os

def create_dir(dir):
    """Function that creates a directory.
    
    Parameters
    ----------
    dir : string
        Name of directory; if False, no directory is created.
        
    Returns
    ----------
    td : string
        Path to directory.
    """
    
    if dir:
        td = dir
        try:
            if not os.path.isdir(dir):
                os.mkdir(dir)
            if td[-1] is not '/':
                td += '/'
        except:
            print( 'Cannot create output dir')
            td = ''
    else:
        td = ''
    return td

################
# Config class
################

class Config():
    """Class for TBPM parameters.
    
    Attributes
    ----------
    generic['Bessel_max'] : int
        Maximum number of Bessel functions. Default value: 100
    generic['Bessel_precision'] : float
        Bessel function precision cut-off. Default value: 1.0e-13
    generic['energy_range'] : float
        Energy range in eV, centered at 0. If False, energy range 
        is computed automatically. Default value: False.
    generic['correct_spin'] : bool
        If True, results are corrected for spin. Default value: False.
    generic['nr_time_steps'] : int
        Number of time steps. Default value: 1024
    generic['nr_ran_samples'] : int
        Number of random initial wave functions. Default value: 1
    generic['beta'] : float
        Value for 1/kT. 
        Default value: 11604.505/300 (room temperature, using eV)
    generic['mu'] : float
        Chemical potential. Default value: 0.
    generic['nr_Fermi_fft_steps'] : int
        Maximum number of Fermi-Dirac distribution FFT steps, 
        must be power of two. Default value: 2**15
    generic['Fermi_cheb_precision'] : float
        Precision cut-off of Fermi-Dirac distribution. 
        Default value: 1.0e-10
    generic['seed'] : int
        Seed for random wavefunction generation. Default value: 1337.
    dyn_pol['q_points'] : (n_q_points, 3) list of floats
        List of q-points. Default value: [[0.1, 0., 0.]].
    dyn_pol['coulomb_constant'] : float
        Coulomb constant. Default value: 1.0
    dyn_pol['background_dielectric_constant'] : float
        Background dielectric constant. Default value: 23.6.
    quasi_eigenstates['energies'] : list of floats
        List of energies of quasi-eigenstates. Default value: [-0.1, 0., 0.1].
    output['timestamp'] : int
        Timestamp generated at __init__ call to make output 
        files unique.
    output['directory'] : string
        Output directory. Default value: "sim_data".
    output['corr_DOS'] : string
        DOS correlation output file. 
        Default value: "sim_data/" + timestamp + "corr_DOS.dat".
    output['corr_AC'] : string
        AC conductivity correlation output file. 
        Default value: "sim_data/" + timestamp + "corr_AC.dat".
    output['corr_DC'] : string
        DC conductivity correlation output file. 
        Default value: "sim_data/" + timestamp + "corr_DC.dat".
    output['corr_KB_DC'] : string
        Kubo-Bastin DC conductivity correlation output file. 
        Default value: "sim_data/" + timestamp + "corr_KB_DC.dat".
    output['corr_dyn_pol'] : string
        AC conductivity correlation output file. 
        Default value: "sim_data/" + timestamp + "corr_dyn_pol.dat".
    """

    # initialize
    def __init__(self):
    
        # declare dicts
        self.generic = {}
        self.dyn_pol = {}
        self.quasi_eigenstates = {}
        self.output = {}
        
        # generic standard values
        self.generic['Bessel_max'] = 100
        self.generic['Bessel_precision'] = 1.0e-13
        self.generic['energy_range'] = 0. # pick range automatically
        self.generic['correct_spin'] = False
        self.generic['nr_time_steps'] = 1024
        self.generic['nr_random_samples'] = 1
        self.generic['beta'] = 11604.505/300
        self.generic['mu'] = 0.
        self.generic['nr_Fermi_fft_steps'] = 2**15
        self.generic['Fermi_cheb_precision'] = 1.0e-10
        self.generic['seed'] = 1337
        
        # quasi-eigenstates
        self.quasi_eigenstates['energies'] = [-0.1, 0., 0.1]
        
        # dynamical polarization
        self.dyn_pol['q_points'] = [[1., 0., 0.]]
        self.dyn_pol['coulomb_constant'] = 1.0
        self.dyn_pol['background_dielectric_constant'] = 2 * np.pi * 3.7557757
        
        # output settings
        self.output['timestamp'] = str(int(time.time()))
        self.set_output('sim_data', self.output['timestamp'])
    
    def set_output(self, directory = False, prefix = ""):
        """Function to set data output options.
        
        This function will set self.output['directory'] and correlation 
        file names for automised data output.
        
        Parameters
        ----------
        directory : string, optional
            output directory, set to False if you don't want to specify
            an output directory
        prefix : string, optional
            prefix for filenames
        """
        
        td = create_dir(directory)
        self.output['directory'] = td
        self.output['corr_DOS'] = td + prefix + 'corr_DOS' + '.dat'
        self.output['corr_AC'] = td + prefix + 'corr_AC' + '.dat'
        self.output['corr_dyn_pol'] = td + prefix + 'dyn_pol' + '.dat'
        self.output['corr_DC'] = td + prefix + 'corr_DC' + '.dat'
        self.output['corr_KB_DC'] = td + prefix + 'corr_KB_DC' + '.dat'
    
    def save(self, filename = "config.pkl", directory = False, prefix = ""):
        """Function to save config parameters to a .pkl file.
        
        Parameters
        ----------
        directory : string, optional
            output directory, set to False if you don't want to specify
            an output directory
        filename : string, optional
            file name
        suffix : string, optional
            suffix for filenames
        """
        
        td = create_dir(directory)
        with open(td + prefix + filename, 'wb') as f:
            pickle.dump(self, f, pickle.HIGHEST_PROTOCOL)
