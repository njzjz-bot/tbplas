#! /usr/bin/env python

import math

import numpy as np
from numpy.linalg import norm

import tbplas as tb


def calc_twist_angle(i):
    """
    Calculate twisting angle according to ref. [1].

    :param i: integer
        parameter controlling the twisting angle
    :return: float
        twisting angle in RADIANs, NOT degrees
    """
    cos_ang = (3 * i ** 2 + 3 * i + 0.5) / (3 * i ** 2 + 3 * i + 1)
    return math.acos(cos_ang)


def calc_twist_angle2(n, m):
    """
    Calculate twisting angle according to ref. [2].

    :param n: integer
        parameter controlling the twisting angle
    :param m: integer
        parameter controlling the twisting angle
    :return: float
        twisting angle in RADIANs, NOT degrees
    """
    cos_ang = (n**2 + 4 * n * m + m**2) / (2 * (n**2 + n * m + m**2))
    return math.acos(cos_ang)


def calc_hetero_lattice(i, prim_cell_fixed: tb.PrimitiveCell):
    """
    Calculate Cartesian coordinates of lattice vectors of hetero-structure
    according to ref. [1].

    :param i: integer
        parameter controlling the twisting angle
    :param prim_cell_fixed: instance of 'PrimitiveCell' class
        primitive cell of fixed layer
    :return: hetero_lattice: (3, 3) float64 array
        Cartesian coordinates of hetero-structure lattice vectors in NANOMETER
    """
    hetero_lattice = np.array([[i, i + 1, 0],
                               [-(i + 1), 2 * i + 1, 0],
                               [0, 0, 1]])
    hetero_lattice = tb.frac2cart(prim_cell_fixed.lat_vec, hetero_lattice)
    return hetero_lattice


def calc_hetero_lattice2(n, m, prim_cell_fixed: tb.PrimitiveCell):
    """
    Calculate Cartesian coordinates of lattice vectors of hetero-structure
    according to ref. [2].

    :param n: integer
        parameter controlling the twisting angle
    :param m: integer
        parameter controlling the twisting angle
    :param prim_cell_fixed: instance of 'PrimitiveCell' class
        primitive cell of fixed layer
    :return: hetero_lattice: (3, 3) float64 array
        Cartesian coordinates of hetero-structure lattice vectors in NANOMETER
    """
    hetero_lattice = np.array([[n, m, 0],
                               [-m, n + m, 0],
                               [0, 0, 1]])
    hetero_lattice = tb.frac2cart(prim_cell_fixed.lat_vec, hetero_lattice)
    return hetero_lattice


def calc_hop(rij: np.ndarray):
    """
    Calculate hopping parameter according to Slater-Koster relation.
    See ref. [2] for the formulae.

    :param rij: (3,) array
        displacement vector between two orbitals in NM
    :return: hop: float
        hopping parameter
    """
    a0 = 0.1418
    a1 = 0.3349
    r_c = 0.6140
    l_c = 0.0265
    gamma0 = 2.7
    gamma1 = 0.48
    decay = 22.18
    q_pi = decay * a0
    q_sigma = decay * a1
    dr = norm(rij).item()
    n = rij.item(2) / dr
    v_pp_pi = - gamma0 * math.exp(q_pi * (1 - dr / a0))
    v_pp_sigma = gamma1 * math.exp(q_sigma * (1 - dr / a1))
    fc = 1 / (1 + math.exp((dr - r_c) / l_c))
    hop = (n**2 * v_pp_sigma + (1 - n**2) * v_pp_pi) * fc
    return hop


def extend_hop(prim_cell: tb.PrimitiveCell, max_distance=0.75):
    """
    Extend the hopping terms in primitive cell up to cutoff distance.

    :param prim_cell: tb.PrimitiveCell
        primitive cell to extend
    :param max_distance: cutoff distance in NM
    :return: None. Incoming primitive cell is modified
    """
    neighbors = tb.find_neighbors(prim_cell, a_max=1, b_max=1,
                                  max_distance=max_distance)
    for term in neighbors:
        i, j = term.pair
        prim_cell.add_hopping(term.rn, i, j, calc_hop(term.rij))


def main():
    # In this tutorial we show how to build twisted bilayer graphene. Firstly, we need
    # to define the functions for evaluating twisting angle and coordinates of lattice
    # vectors. See the following papers for the formulae:
    #
    # [1] https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.99.256802
    # [2] https://journals.aps.org/prb/abstract/10.1103/PhysRevB.86.125413
    #
    # See function 'calc_twist_angle', 'calc_twist_angle2', 'calc_hetero_lattice' and
    # 'calc_hetero_lattice2' for the implementation.

    # Evaluate twisting angle.
    i = 5
    angle = calc_twist_angle(i)

    # To build a twist bilayer graphene we build the twisted primitive cells for
    # each layer first. The 'fixed' cell which is fixed at z=0 and not rotated
    # can be imported from the material repository directly.
    prim_cell_fixed = tb.make_graphene_diamond()

    # On the contrary, the 'twisted' cell must be rotated counter-clockwise by
    # the twisting angle and shifted towards +z by 0.3349 nanometers, which is
    # done by calling the function 'spiral_prim_cell'.
    prim_cell_twisted = tb.make_graphene_diamond()
    tb.spiral_prim_cell(prim_cell_twisted, angle=angle, shift=0.3349)

    # Evaluate coordinates of lattice vectors of hetero-structure.
    # The reference papers give the fractional coordinates in basis of 'fixed'
    # primitive cell. However, we want the Cartesian coordinates. This is done
    # by calling the 'calc_hetero_lattice' function.
    hetero_lattice = calc_hetero_lattice(i, prim_cell_fixed)

    # With all the primitive cells ready, we build the 'fixed' and 'twisted'
    # layers by reshaping corresponding cells to the lattice vectors of
    # hetero-structure. This is done by calling 'make_hetero_layer'.
    layer_fixed = tb.make_hetero_layer(prim_cell_fixed, hetero_lattice)
    layer_twisted = tb.make_hetero_layer(prim_cell_twisted, hetero_lattice)

    # From now, we have two approaches to build the hetero-structure.
    # The first one is to merge the layers and then extend the hopping terms of
    # the whole cell.
    algo = 0
    if algo == 0:
        merged_cell = tb.merge_prim_cell(layer_fixed, layer_twisted)
        extend_hop(merged_cell, max_distance=0.75)

    # The second approach is complex, but more general. We build the inter-cell
    # hopping terms first, then extend the layers. Finally, we merge them to
    # yield the hetero-structure.
    else:
        # Find the hopping neighbors between 'fixed' and 'twisted' layers up to
        # cutoff distance. We only need to take the hopping terms from (0, 0, 0)
        # cell of 'fixed' layer to any cell of 'twisted' layer. The conjugate
        # terms are handled automatically.
        inter_hop = tb.PCInterHopping(layer_fixed, layer_twisted)
        neighbors = tb.find_neighbors(layer_fixed, layer_twisted,
                                      a_max=1, b_max=1, max_distance=0.75)
        for term in neighbors:
            i, j = term.pair
            inter_hop.add_hopping(term.rn, i, j, calc_hop(term.rij))

        # Then we need to extend the hopping terms in each layer up to cutoff
        # distance by calling 'extend_intra_hop'.
        extend_hop(layer_fixed, max_distance=0.75)
        extend_hop(layer_twisted, max_distance=0.75)

        # Finally, we merge layers and inter_hop to yield a hetero-structure
        merged_cell = tb.merge_prim_cell(layer_fixed, layer_twisted, inter_hop)

    # Evaluate band structure of hetero-structure
    k_points = np.array([
       [0.0, 0.0, 0.0],
       [2./3, 1./3, 0.0],
       [1./2, 0.0, 0.0],
       [0.0, 0.0, 0.0],
    ])
    k_label = ["G", "K", "M", "G"]
    k_path, k_idx = tb.gen_kpath(k_points, [10, 10, 10])
    k_len, bands = merged_cell.calc_bands(k_path)
    vis = tb.Visualizer()
    vis.plot_bands(k_len, bands, k_idx, k_label)

    # Visualize Moire's pattern
    angle = -math.atan(hetero_lattice[0, 1] / hetero_lattice[0, 0])
    tb.spiral_prim_cell(merged_cell, angle=angle)
    sample = tb.Sample(tb.SuperCell(merged_cell, dim=(4, 4, 1),
                                    pbc=(True, True, False)))
    sample.plot(with_orbitals=False, hop_as_arrows=False,
                hop_eng_cutoff=0.3)


if __name__ == "__main__":
    main()
