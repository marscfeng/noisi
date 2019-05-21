import numpy as np
from obspy.signal.invsim import cosine_taper
import h5py
import yaml
import time
from glob import glob
import os
import io
from scipy.fftpack import next_fast_len
import errno
from noisi_v1 import WaveField
from noisi_v1.util.geo import is_land, geographical_distances
from noisi_v1.util.geo import get_spherical_surface_elements
from noisi_v1.util.plot import plot_grid
import matplotlib.pyplot as plt
from math import pi, sqrt
from warnings import warn


class source_setup(object):

    def __init__(self, args):

        if os.path.exists(args.source_model):
            self.setup_source_startingmodel(args)
        else:
            self.initialize_source(args)

    def initialize_source(self, args):
        source_model = args.source_model
        project_path = os.path.dirname(source_model)
        noisi_path = os.path.abspath(os.path.dirname(
                                     os.path.dirname(__file__)))
        config_filename = os.path.join(project_path, 'config.yml')

        if not os.path.exists(config_filename):
            raise FileNotFoundError(errno.ENOENT,
                                    os.strerror(errno.ENOENT) +
                                    "\nRun setup_project first.",
                                    config_filename)

        # set up the directory structure:
        os.mkdir(source_model)
        os.mkdir(os.path.join(source_model, 'observed_correlations'))
        for d in ['adjt', 'corr', 'kern']:
            os.makedirs(os.path.join(source_model, 'iteration_0', d))

        # set up the source model configuration file
        with io.open(os.path.join(noisi_path,
                                  'config', 'source_config.yml'), 'r') as fh:
            conf = yaml.safe_load(fh)
            conf['date_created'] = str(time.strftime("%Y.%m.%d"))
            conf['project_name'] = os.path.basename(project_path)
            conf['project_path'] = os.path.abspath(project_path)
            conf['source_name'] = os.path.basename(source_model)
            conf['source_path'] = os.path.abspath(source_model)
            conf['source_setup_file'] = os.path.join(conf['source_path'],
                                              'source_setup_parameters.yml')

        with io.open(os.path.join(noisi_path,
                                  'config',
                                  'source_config_comments.txt'), 'r') as fh:
            comments = fh.read()

        with io.open(os.path.join(source_model,
                                  'source_config.yml'), 'w') as fh:
            cf = yaml.safe_dump(conf, sort_keys=False, indent=4)
            fh.write(cf)
            fh.write(comments)

        # set up the measurements configuration file
        with io.open(os.path.join(noisi_path,
                                  'config', 'measr_config.yml'), 'r') as fh:
            conf = yaml.safe_load(fh)
            conf['date_created'] = str(time.strftime("%Y.%m.%d"))
        with io.open(os.path.join(noisi_path,
                                  'config',
                                  'measr_config_comments.txt'), 'r') as fh:
            comments = fh.read()

        with io.open(os.path.join(source_model,
                                  'measr_config.yml'), 'w') as fh:
            cf = yaml.safe_dump(conf, sort_keys=False, indent=4)
            fh.write(cf)
            fh.write(comments)

        # set up the measurements configuration file
        with io.open(os.path.join(noisi_path,
                                  'config',
                                  'source_setup_parameters.yml'), 'r') as fh:
            setup = yaml.safe_load(fh)

        with io.open(os.path.join(source_model,
                                  'source_setup_parameters.yml'), 'w') as fh:
            stup = yaml.safe_dump(setup, sort_keys=False, indent=4)
            fh.write(stup)

        os.system('cp ' +
                  os.path.join(noisi_path, 'config', 'stationlist.csv ') +
                  source_model)

        print("Copied default source_config.yml, source_setup_parameters.yml \
and measr_config.yml to source model directory, please edit and rerun.")
        return()

    def setup_source_startingmodel(self, args):
        # plotting:
        colors = ['purple', 'g', 'b', 'orange']
        colors_cmaps = [plt.cm.Purples, plt.cm.Greens, plt.cm.Blues,
                        plt.cm.Oranges]

        with io.open(os.path.join(args.source_model,
                                  'source_config.yml'), 'r') as fh:
            source_conf = yaml.safe_load(fh)

        with io.open(os.path.join(source_conf['project_path'],
                                  'config.yml'), 'r') as fh:
            conf = yaml.safe_load(fh)

        with io.open(source_conf['source_setup_file'], 'r') as fh:
            parameter_sets = yaml.safe_load(fh)
            if conf['verbose']:
                print(parameter_sets)

        # load the source locations of the grid
        grd = np.load(os.path.join(conf['project_path'],
                                   'sourcegrid.npy'))
        # add the approximate spherical surface elements
        if grd.shape[-1] < 50000:
            surf_el = get_spherical_surface_elements(grd[0], grd[1])
        else:
            warn('Large grid; surface element computation slow. Using \
approximate surface elements.')
            surf_el = np.ones(grd.shape[-1]) * conf['grid_dx'] ** 2

        wfs = glob(os.path.join(conf['project_path'], 'greens', '*.h5'))
        if wfs != [] and conf['verbose']:
            print('Found wavefield.')
        else:
            raise FileNotFoundError('No wavefield database found. Run \
precompute_wavefield first.')

        with WaveField(wfs[0]) as wf:
            df = wf.stats['Fs']
            nt = wf.stats['nt']

        n = next_fast_len(2 * nt - 1)
        freq = np.fft.rfftfreq(n, d=1. / df)
        n_distr = len(parameter_sets)
        coeffs = np.zeros((grd.shape[-1], n_distr))
        spectra = np.zeros((n_distr, len(freq)))

        # fill in the distributions and the spectra
        for i in range(n_distr):
            coeffs[:, i] = self.distribution_from_parameters(grd,
                                                             parameter_sets[i],
                                                             conf['verbose'])
            if not parameter_sets[i]['distribution'] == 'gaussian_blob':
                coeffs[:, i] /= surf_el
            # plot
            outfile = os.path.join(args.source_model,
                                   'source_starting_model_distr%g.png' % i)
            plot_grid(grd[0], grd[1], coeffs[:, i],
                      outfile=outfile, cmap=colors_cmaps[i],
                      sequential=True, normalize=False,
                      quant_unit='Spatial weight (-)')

            spectra[i, :] = self.spectrum_from_parameters(freq,
                                                          parameter_sets[i])

        # plotting the spectra
        fig1 = plt.figure()
        ax = fig1.add_subplot('111')
        for i in range(n_distr):
            ax.plot(freq, spectra[i, :] / spectra.max(), color=colors[i])

        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Rel. PSD norm. to strongest spectrum (-)')
        fig1.savefig(os.path.join(args.source_model,
                                  'source_starting_model_spectra.png'))
        # Save to an hdf5 file
        with h5py.File(os.path.join(args.source_model, 'iteration_0',
                                    'starting_model.h5'), 'w') as fh:
            fh.create_dataset('coordinates', data=grd)
            fh.create_dataset('frequencies', data=freq)
            fh.create_dataset('model', data=coeffs.astype(np.float32))
            fh.create_dataset('spectral_basis',
                              data=spectra.astype(np.float32))
            fh.create_dataset('surface_areas',
                              data=surf_el.astype(np.float32))

    def distribution_from_parameters(self, grd, parameters, verbose=False):

        if parameters['distribution'] == 'homogeneous':
            if verbose:
                print('homogeneous distribution')
            distribution = np.ones(grd.shape[-1])
            distribution /= grd.shape[-1]
            return(distribution)

        elif parameters['distribution'] == 'ocean':
            if verbose:
                print('ocean-only distribution')
            is_ocean = np.abs(is_land(grd[0], grd[1]) - 1.)
            distribution = is_ocean / is_ocean.sum()
            return(distribution)

        elif parameters['distribution'] == 'gaussian_blob':
            if verbose:
                print('gaussian blob')
            dist = geographical_distances(grd,
                                          parameters['center_latlon']) / 1000.
            sigma_km = parameters['sigma_m'] / 1000.
            blob = np.exp(-(dist ** 2) / (2 * sigma_km ** 2))
            # normalize for a 2-D Gaussian function
            # important: Use sigma in m because the surface elements are in m
            norm_factor = 1. / ((sigma_km * 1000.) ** 2 * 2. * np.pi)
            blob *= norm_factor

            if parameters['only_in_the_ocean']:
                is_ocean = np.abs(is_land(grd[0], grd[1]) - 1.)
                blob *= is_ocean
                blob *= (grd.shape[-1] / is_ocean.sum())

            return(blob)

    def spectrum_from_parameters(self, freq, parameters):

        mu = parameters['mean_frequency_Hz']
        sig = parameters['standard_deviation_Hz']
        taper = cosine_taper(len(freq), parameters['taper_percent'] / 100.)
        spec = taper * np.exp(-((freq - mu) ** 2) /
                              (2 * sig ** 2))
        spec = spec / (sig * sqrt(2. * pi))
        spec *= parameters['weight']

        return(spec)