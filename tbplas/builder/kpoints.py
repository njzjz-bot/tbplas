"""
Functions for k-point operations.

Functions
---------
    gen_kpath: user function
        generate path in the reciprocal space connecting highly symmetric
        k-points
    gen_kdist: user function
       convert kpath generated by gen_path into distances in reciprocal space
    gen_kmesh: user function
       generate uniform mesh grid in the first Brillouin zone
"""

import numpy as np

from .lattice import gen_reciprocal_vectors, frac2cart


def gen_kpath(hs_kpoints, num_interp):
    """
    Generate path in the reciprocal space connecting highly symmetric k-points.

    :param hs_kpoints: (nk, 3) float64 array
        fractional coordinates of highly symmetric k-points
    :param num_interp: (nk-1,) int32 array
        numbers of intermediate k-points between two highly symmetric k-points
    :return: kpath: (sum(num_interp)+1, 3) float64 array
        fractional coordinates of k-points along the path
    :return: hs_index: (nk,) int32 array
        indices of highly symmetric k-points in kpath
    :raise ValueError: if len(num_interp) != nk - 1
    """
    if not isinstance(hs_kpoints, np.ndarray):
        hs_kpoints = np.array(hs_kpoints)
    if hs_kpoints.shape[0] != len(num_interp) + 1:
        raise ValueError("Length of num_interp should be nk-1")
    kpath = []
    for i in range(len(num_interp)):
        k0 = hs_kpoints[i]
        k1 = hs_kpoints[i+1]
        nk = num_interp[i]
        for j in range(nk):
            kpath.append(k0 + j * 1.0 / nk * (k1 - k0))
    kpath.append(hs_kpoints[-1])
    hs_index = [sum(num_interp[:_]) for _ in range(len(num_interp)+1)]
    return np.array(kpath), np.asarray(hs_index)


def gen_kdist(lattice_vectors, kpoints):
    """
    Convert k_path generated by gen_path into distances in reciprocal space.

    :param lattice_vectors: (3, 3) float64 array
        Cartesian coordinates of lattice vectors
    :param kpoints: (nk, 3) float64 array
        fractional coordinates of kpoints
    :return: kdist: (nk,) float64 array
        distance in reciprocal space in unit of reciprocal lattice vectors
    """
    reciprocal_vectors = gen_reciprocal_vectors(lattice_vectors)
    kpoints_cartesian = frac2cart(reciprocal_vectors, kpoints)
    kdist = np.zeros(kpoints.shape[0])
    for i in range(1, kpoints.shape[0]):
        dk = kpoints_cartesian[i] - kpoints_cartesian[i-1]
        kdist[i] = kdist[i-1] + np.sqrt(np.sum(dk**2))
    return kdist


def gen_kmesh(grid_size):
    """
    Generate uniform mesh grid in the first Brillouin zone.

    :param grid_size: (na, nb, nc)
        dimension of mesh grid along three directions
    :return: kmesh: (na*nb*nc, 3) float64 array
        fractional coordinates of kpoints in the grid
    :raise ValueError: if len(grid_size) != 3
    """
    if len(grid_size) != 3:
        raise ValueError("Length of grid_size should be 3")
    kmesh = np.array([[kx, ky, kz]
                     for kx in np.linspace(0, 1-1./grid_size[0], grid_size[0])
                     for ky in np.linspace(0, 1-1./grid_size[1], grid_size[1])
                     for kz in np.linspace(0, 1-1./grid_size[2], grid_size[2])])
    return kmesh
