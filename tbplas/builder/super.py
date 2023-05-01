"""Functions and classes for supercell."""

from typing import Callable, List, Tuple, Union

import numpy as np
import matplotlib.pyplot as plt

from ..base import lattice as lat
from . import exceptions as exc
from . import core
from .base import (check_rn, check_pbc, Lockable, IntraHopping, rn_type,
                   pbc_type, id_pc_type)
from .primitive import PrimitiveCell
from .utils import ModelViewer


class OrbitalSet(Lockable):
    """
    Container class for orbitals and vacancies in the supercell.

    Attributes
    ----------
    prim_cell: 'PrimitiveCell' instance
        primitive cell from which the supercell is constructed
    dim: (3,) int32 array
        dimension of the supercell along a, b, and c directions
    pbc: (3,) int32 array
        whether to enable periodic condition along a, b, and c directions
        0 for False, 1 for True.
    vacancy_list: List[Tuple[int, int, int, int]]
        indices of vacancies in primitive cell representation (ia, ib, ic, io)
        None if there are no vacancies.
    hash_dict: Dict[str, int]
        dictionary of hash of tuple(vacancy_list)
        hashes of attributes to be used by 'sync_array' to update the arrays
    vac_id_pc: (num_vac, 4) int32 array
        indices of vacancies in primitive cell representation
    vac_id_sc: (num_vac,) int64 array
        indices of vacancies in supercell representation
    orb_id_pc: (num_orb_sc, 4) int32 array
        indices of orbitals in primitive cell representation

    NOTES
    -----
    1. Minimal supercell dimension

    Assume that we have a primitive cell located at R=0. The furthest primitive
    cell between which hopping terms exist is located at R=N. It can be proved
    that if the dimension of supercell along that direction is less than N,
    the same matrix element hij will appear more than one time in hop_i, hop_j
    and hop_v of 'SuperCell' class, as well as its conjugate counterpart. This
    will complicate the program and significantly slow it down, which situation
    we must avoid.

    Further, if the dimension of supercell falls in [N, 2*N], hij will appear
    only one time, yet its conjugate counterpart still exists. Although no
    problems have been found so far, we still need to avoid this situation.

    So the minimal dimension of supercell is 2*N+1, where N is the index of
    the furthest primitive cell between which hopping terms exists. Otherwise,
    the 'SuperCell' class, as well as the core functions of '_get_num_hop_sc',
    'build_hop', 'build_hop_k' and 'fill_ham' will not work properly.

    In the hr.dat file produced by Wannier90, there is an N_min and an N_max
    for the furthest primitive cell index. In that case, N should be the
    maximum of |N_max| and |N_min| as the result of translational symmetry.

    2. Why not orb_id_sc

    It's unnecessary to have the orb_id_sc array, as it can be generated from
    orb_id_pc on-the-fly. Actually, the vac_id_sc array is also unnecessary,
    as it can also be generated from vac_id_pc. We keep it just to accelerate
    some operations. For orb_id_sc, there is no such need, and we do not keep
    it for reduce memory usage.

    However, it should be noted that vac_id_sc and orb_id_sc are generated via
    different approaches. We show it by an example of 2*2 supercell with 2
    orbitals per primitive cell. The indices of orbitals as well as vacancies
    in primitive cell representation are
               id_pc    id_sc    type
        (0, 0, 0, 0)        0     orb
        (0, 0, 0, 1)        1     vac
        (0, 1, 0, 0)        2     vac
        (0, 1, 0, 1)        3     orb
        (1, 0, 0, 0)        4     orb
        (1, 0, 0, 1)        5     vac
        (1, 0, 0, 0)        6     orb
        (1, 0, 0, 1)        7     orb

    The indices for vacancies in sc representation are the original id_sc, i.e.
    1, 2, and 5. However, the indices for orbitals are re-ordered to be
               id_pc    id_sc    type
        (0, 0, 0, 0)        0     orb
        (0, 1, 0, 1)        1     orb
        (1, 0, 0, 0)        2     orb
        (1, 0, 0, 0)        3     orb
        (1, 0, 0, 1)        4     orb
    In the core module, indices of vacancies are generated by _id_pc2sc while
    indices of orbitals are generated by _id_pc2sc_vac. The latter excludes
    vacancies when generating the indices.
    """
    def __init__(self, prim_cell: PrimitiveCell,
                 dim: rn_type,
                 pbc: pbc_type = (False, False, False),
                 vacancies: Union[List[id_pc_type], np.ndarray] = None) -> None:
        """
        :param prim_cell: primitive cell from which the supercell is constructed
        :param dim: dimension of the supercell along a, b and c directions
        :param pbc: whether to enable periodic boundary condition along a, b,
            and c directions
        :param vacancies: list of indices of vacancies in primitive cell
            representation
        :raises SCDimLenError: if len(dim) != 2 or 3
        :raises SCDimSizeError: if dimension is smaller than minimal value
        :raises PBCLenError: if len(pbc) != 2 or 3
        :raises VacIDPCLenError: if any vacancy does not have right length
        :raises VacIDPCIndexError: if cell or orbital index of any vacancy is
            out of range
        """
        super().__init__()

        # Synchronize and lock primitive cell
        self.prim_cell = prim_cell
        self.prim_cell.sync_array()
        self.prim_cell.lock()

        # Check and set dimension
        dim, legal = check_rn(dim, complete_item=1)
        if not legal:
            raise exc.SCDimLenError(dim)
        for i in range(3):
            rn_min = self.prim_cell.hop_ind[:, i].min()
            rn_max = self.prim_cell.hop_ind[:, i].max()
            dim_min = max(abs(rn_min), abs(rn_max))
            if dim[i] < dim_min:
                raise exc.SCDimSizeError(i, dim_min)
        self.dim = np.array(dim, dtype=np.int32)

        # Check and set periodic boundary condition
        pbc, legal = check_pbc(pbc, complete_item=False)
        if not legal:
            raise exc.PBCLenError(pbc)
        self.pbc = np.array([1 if _ else 0 for _ in pbc], dtype=np.int32)

        # Initialize lists and arrays assuming no vacancies
        self.vacancy_list = []
        self.hash_dict = {'vac': self._get_hash('vac')}
        self.vac_id_pc = None
        self.vac_id_sc = None
        self.orb_id_pc = core.build_orb_id_pc(self.dim, self.num_orb_pc,
                                              self.vac_id_pc)

        # Set vacancies if any
        if vacancies is not None:
            self.add_vacancies(vacancies)

    def _get_hash(self, attr: str) -> int:
        """
        Get hash of given attribute.

        :param attr: name of the attribute
        :return: hash of the attribute
        :raises ValueError: if attr is illegal
        """
        if attr == "vac":
            new_hash = hash(tuple(self.vacancy_list))
        else:
            raise ValueError(f"Illegal attribute name {attr}")
        return new_hash

    def _update_hash(self, attr: str) -> bool:
        """
        Compare and update hash of given attribute.

        :param attr: name of the attribute
        :return: whether the hash has been updated
        :raises ValueError: if attr is illegal
        """
        new_hash = self._get_hash(attr)
        if self.hash_dict[attr] != new_hash:
            self.hash_dict[attr] = new_hash
            status = True
        else:
            status = False
        return status

    def _check_id_pc(self, id_pc: Union[id_pc_type, np.ndarray]) -> None:
        """
        Checks if orbital or vacancy index in primitive cell representation
        is legal.

        A legal id_pc should have cell indices falling within 0 <= rn < dim and
        orbital index falling within 0 <= ib < num_orb_pc.

        :param id_pc: (ia, ib, ic, io) or equivalent int32 array
            orbital or vacancy index in primitive cell representation
        :return: None
        :raises IDPCLenError: if len(id_pc) != 4
        :raises IDPCIndexError: if cell or orbital index of id_pc is
            out of range
        :raises IDPCTypeError: if id_pc is not tuple or numpy array
        """
        if len(id_pc) != 4:
            raise exc.IDPCLenError(id_pc)
        if isinstance(id_pc, tuple):
            for i in range(3):
                if id_pc[i] not in range(self.dim.item(i)):
                    raise exc.IDPCIndexError(i, id_pc)
            if id_pc[3] not in range(self.num_orb_pc):
                raise exc.IDPCIndexError(3, id_pc)
        elif isinstance(id_pc, np.ndarray):
            for i in range(3):
                if id_pc.item(i) not in range(self.dim.item(i)):
                    raise exc.IDPCIndexError(i, id_pc)
            if id_pc.item(3) not in range(self.num_orb_pc):
                raise exc.IDPCIndexError(3, id_pc)
        else:
            raise exc.IDPCTypeError(id_pc)

    def check_lock(self) -> None:
        """Check lock state of this instance."""
        if self.is_locked:
            raise exc.SCLockError()

    def add_vacancy(self, vacancy: Union[id_pc_type, np.ndarray],
                    sync_array: bool = False,
                    **kwargs) -> None:
        """
        Wrapper over 'add_vacancies' to add a single vacancy to the orbital set.

        :param vacancy: (ia, ib, ic, io) or equivalent int32 array
            vacancy index in primitive cell representation
        :param sync_array: whether to call 'sync_array' to update the arrays
        :param kwargs: arguments for method 'sync_array'
        :return: None
        :raises SCLockError: if the object is locked
        :raises VacIDPCLenError: if length of vacancy index is not 4
        :raises VacIDPCIndexError: if cell or orbital index of vacancy is
            out of range
        """
        self.add_vacancies([vacancy], sync_array=sync_array, **kwargs)

    def add_vacancies(self, vacancies: Union[List[id_pc_type], np.ndarray],
                      sync_array: bool = True,
                      **kwargs) -> None:
        """
        Add a list of vacancies to the orbital set.

        :param vacancies: list of (ia, ib, ic, io) or equivalent int32 arrays
            list of indices of vacancies in primitive cell representation
        :param sync_array: whether to call 'sync_array' to update the arrays
        :param kwargs: arguments for method 'sync_array'
        :return: None
        :raises SCLockError: if the object is locked
        :raises VacIDPCLenError: if length of vacancy index is not 4
        :raises VacIDPCIndexError: if cell or orbital index of vacancy is
            out of range
        """
        self.check_lock()

        for vacancy in vacancies:
            # Convert and check vacancy
            if not isinstance(vacancy, tuple):
                vacancy = tuple(vacancy)
            try:
                self._check_id_pc(vacancy)
            except exc.IDPCLenError as err:
                raise exc.VacIDPCLenError(err.id_pc) from err
            except exc.IDPCIndexError as err:
                raise exc.VacIDPCIndexError(err.i_dim, err.id_pc) from err

            # Add vacancy
            if vacancy not in self.vacancy_list:
                self.vacancy_list.append(vacancy)

        if sync_array:
            self.sync_array(**kwargs)

    def set_vacancies(self, vacancies: Union[List[id_pc_type], np.ndarray] = None,
                      sync_array: bool = True,
                      **kwargs) -> None:
        """
        Reset the list of vacancies to given ones.

        :param vacancies: list of (ia, ib, ic, io) or equivalent int32 arrays
            list of indices of vacancies in primitive cell representation
        :param sync_array: whether to call 'sync_array' to update the arrays
        :param kwargs: arguments for method 'sync_array'
        :return: None
        :raises SCLockError: if the object is locked
        :raises VacIDPCLenError: if length of vacancy index is not 4
        :raises VacIDPCIndexError: if cell or orbital index of vacancy is
            out of range
        """
        self.vacancy_list = []
        self.add_vacancies(vacancies, sync_array=sync_array, **kwargs)

    def sync_array(self, verbose: bool = False,
                   force_sync: bool = False) -> None:
        """
        Synchronize vac_id_pc, vac_id_sc and orb_id_pc according to
        vacancy_list.

        NOTE: The core function '_id_pc2sc_vac' requires vac_id_sc to be sorted
        in increasing order. Otherwise, it won't work properly! So we must sort
        it here. We also re-order vac_id_pc accordingly to avoid potential bugs.

        :param verbose: whether to output additional debugging information
        :param force_sync: whether to force synchronizing the arrays even if
            vacancy_list did not change
        :return: None
        """
        to_update = self._update_hash('vac')
        if force_sync or to_update:
            if verbose:
                print("INFO: updating sc vacancy and orbital arrays")
            # If vacancy list is not [], update arrays as usual.
            if len(self.vacancy_list) != 0:
                vac_id_pc = np.array(self.vacancy_list, dtype=np.int32)
                vac_id_sc = core.build_vac_id_sc(self.dim, self.num_orb_pc,
                                                 vac_id_pc)
                sorted_idx = np.argsort(vac_id_sc, axis=0)
                self.vac_id_pc = vac_id_pc[sorted_idx]
                self.vac_id_sc = vac_id_sc[sorted_idx]
                self.orb_id_pc = core.build_orb_id_pc(self.dim, self.num_orb_pc,
                                                      self.vac_id_pc)
            # Otherwise, restore to default settings as in __ini__.
            else:
                self.vac_id_pc = None
                self.vac_id_sc = None
                self.orb_id_pc = core.build_orb_id_pc(self.dim, self.num_orb_pc,
                                                      self.vac_id_pc)
        else:
            if verbose:
                print("INFO: no need to update sc vacancy and orbital arrays")

    def orb_id_sc2pc(self, id_sc: int) -> np.ndarray:
        """
        Convert orbital (NOT VACANCY) index from sc representation to pc
        representation.

        NOTE: This method is safe, but EXTREMELY SLOW. If you are going to
        call this method many times, use orb_id_sc2pc_array instead.

        :param id_sc: index of orbital in supercell representation
        :return: (4,) int32 array
            index of orbital in primitive cell representation
        :raises IDSCIndexError: if id_sc is out of range
        """
        self.sync_array()
        try:
            id_pc = self.orb_id_pc[id_sc]
        except IndexError as err:
            raise exc.IDSCIndexError(id_sc) from err
        return id_pc

    def orb_id_pc2sc(self, id_pc: Union[id_pc_type, np.ndarray]) -> int:
        """
        Convert orbital (NOT VACANCY) index from pc representation to sc
        representation.

        NOTE: This method is safe, but EXTREMELY SLOW. If you are going to
        call this method many times, use orb_id_pc2sc_array instead.

        :param id_pc: (ia, ib, ic, io), or equivalent int32 array
            index of orbital in primitive cell representation
        :return: index of orbital in supercell representation
        :raises IDPCLenError: if len(id_pc) != 4
        :raises IDPCIndexError: if cell or orbital index of id_pc is
            out of range
        :raises IDPCTypeError: if id_pc is not tuple or numpy array
        :raises IDPCVacError: if id_pc corresponds to a vacancy
        """
        self.sync_array()
        self._check_id_pc(id_pc)
        if not isinstance(id_pc, np.ndarray) or id_pc.dtype != np.int32:
            id_pc = np.array(id_pc, dtype=np.int32)
        orb_id_sc = core.id_pc2sc(self.dim, self.num_orb_pc,
                                  id_pc, self.vac_id_sc)
        if orb_id_sc == -1:
            raise exc.IDPCVacError(id_pc)
        return orb_id_sc

    def orb_id_sc2pc_array(self, id_sc_array: np.ndarray) -> np.ndarray:
        """
        Convert an array of orbital (NOT VACANCY) indices from sc
        representation to pc representation.

        :param id_sc_array: (num_orb,) int64 array
            orbital indices in supercell representation
        :return: (num_orb, 4) int32 array
            orbital indices in primitive cell representation
        :raises IDSCIndexError: if any id_sc in id_sc_array is out of range
        """
        self.sync_array()
        if not isinstance(id_sc_array, np.ndarray) \
                or id_sc_array.dtype != np.int64:
            id_sc_array = np.array(id_sc_array, dtype=np.int64)
        status = core.check_id_sc_array(self.num_orb_sc, id_sc_array)
        if status[0] == -1:
            raise exc.IDSCIndexError(id_sc_array[status[1]])
        id_pc_array = core.id_sc2pc_array(self.orb_id_pc, id_sc_array)
        return id_pc_array

    def orb_id_pc2sc_array(self, id_pc_array: np.ndarray) -> np.ndarray:
        """
        Convert an array of orbital (NOT VACANCY) indices from pc
        representation to sc representation.

        :param id_pc_array: (num_orb, 4) int32 array
            orbital indices in primitive cell representation
        :return: (num_orb,) int64 array
            orbital indices in supercell representation
        :raises IDPCLenError: if id_pc_array.shape[1] != 4
        :raises IDPCIndexError: if any id_pc in id_pc_array is out of range
        :raises IDPCVacError: if any id_pc in id_pc_array is a vacancy
        """
        self.sync_array()
        if not isinstance(id_pc_array, np.ndarray) \
                or id_pc_array.dtype != np.int32:
            id_pc_array = np.array(id_pc_array, dtype=np.int32)
        if id_pc_array.shape[1] != 4:
            raise exc.IDPCLenError(id_pc_array[0])
        status = core.check_id_pc_array(self.dim, self.num_orb_pc,
                                        id_pc_array, self.vac_id_pc)
        if status[0] == -2:
            raise exc.IDPCIndexError(status[2], id_pc_array[status[1]])
        if status[0] == -1:
            raise exc.IDPCVacError(id_pc_array[status[1]])
        id_sc_array = core.id_pc2sc_array(self.dim, self.num_orb_pc,
                                          id_pc_array, self.vac_id_sc)
        return id_sc_array

    @property
    def num_orb_pc(self) -> int:
        """
        Get the number of orbitals of primitive cell.

        :return: number of orbitals in primitive cell.
        """
        return self.prim_cell.num_orb

    @property
    def num_orb_sc(self) -> int:
        """
        Get the number of orbitals of supercell.

        :return: number of orbitals in supercell
        """
        num_orb_sc = self.num_orb_pc * np.prod(self.dim).item()
        num_orb_sc -= len(self.vacancy_list)
        return num_orb_sc


class SuperCell(OrbitalSet):
    """
    Class for representing a supercell from which the sample is constructed.

    Notes on hop_modifier
    ---------------------
    1. Reduction

    We reduce hopping terms according to the conjugate relation
        <0, bra|H|R, ket> = <0, ket|H|-R, bra>*.
    So actually only half of hopping terms are stored.

    2. Rules

    If the hopping terms claimed here are already included in the supercell,
    they will overwrite the existing terms. If the hopping terms or their
    conjugate counterparts are new to 'SuperCell', they will be appended to
    hop_* arrays. The dr array will also be updated accordingly.

    Attributes
    ----------
    hop_modifier: 'SCIntraHopping' instance
        modification to hopping terms in the supercell
    orb_pos_modifier: function
        modification to orbital positions in the supercell
    """
    def __init__(self, prim_cell: PrimitiveCell,
                 dim: rn_type,
                 pbc: pbc_type = (False, False, False),
                 vacancies: Union[List[id_pc_type], np.ndarray] = None,
                 orb_pos_modifier: Callable[[np.ndarray], None] = None) -> None:
        """
        :param prim_cell: primitive cell from which the supercell is constructed
        :param dim: dimension of the supercell along a, b, and c directions
        :param pbc: whether to enable periodic boundary condition along a, b and
            c directions
        :param vacancies: indices of vacancies in primitive cell representation
        :param orb_pos_modifier: modification to orbital positions in the supercell
        :return: None
        :raises SCDimLenError: if len(dim) != 2 or 3
        :raises SCDimSizeError: if dimension is smaller than minimal value
        :raises PBCLenError: if len(pbc) != 2 or 3
        :raises VacIDPCLenError: if any vacancy does not have right length
        :raises VacIDPCIndexError: if cell or orbital index of any vacancy is
            out of range
        """
        # Build orbital set
        super().__init__(prim_cell, dim, pbc=pbc, vacancies=vacancies)

        # Initialize hop_modifier and orb_pos_modifier
        self.hop_modifier = IntraHopping()
        self.orb_pos_modifier = orb_pos_modifier

    def add_hopping(self, rn: rn_type,
                    orb_i: int,
                    orb_j: int,
                    energy: complex) -> None:
        """
        Add a new term to the hopping modifier.

        :param rn: cell index of the hopping term, i.e. R
        :param orb_i: index of orbital i in <i,0|H|j,R>
        :param orb_j: index of orbital j in <i,0|H|j,R>
        :param energy: hopping integral in eV
        :return: None
        :raises SCLockError: if the supercell is locked
        :raises SCOrbIndexError: if orb_i or orb_j falls out of range
        :raises SCHopDiagonalError: if rn == (0, 0, 0) and orb_i == orb_j
        :raises CellIndexLenError: if len(rn) != 2 or 3
        """
        self.check_lock()

        # Check params, adapted from the '_check_hop_index' method
        # of 'PrimitiveCell' class
        rn, legal = check_rn(rn)
        if not legal:
            raise exc.CellIndexLenError(rn)
        num_orbitals = self.num_orb_sc
        if not (0 <= orb_i < num_orbitals):
            raise exc.SCOrbIndexError(orb_i)
        if not (0 <= orb_j < num_orbitals):
            raise exc.SCOrbIndexError(orb_j)
        if rn == (0, 0, 0) and orb_i == orb_j:
            raise exc.SCHopDiagonalError(rn, orb_i)

        # Add the hopping term
        self.hop_modifier.add_hopping(rn, orb_i, orb_j, energy)

    def set_orb_pos_modifier(self, orb_pos_modifier: Callable = None) -> None:
        """
        Reset orb_pos_modifier.

        :param orb_pos_modifier: modifier to orbital positions
        :return: None
        :raises SCLockError: if the supercell is locked
        """
        self.check_lock()
        self.orb_pos_modifier = orb_pos_modifier

    def get_orb_eng(self) -> np.ndarray:
        """
        Get energies of all orbitals in the supercell.

        :return: (num_orb_sc,) float64 array
            on-site energies of orbitals in the supercell in eV
        """
        self.sync_array()
        return core.build_orb_eng(self.pc_orb_eng, self.orb_id_pc)

    def get_orb_pos(self) -> np.ndarray:
        """
        Get positions of all orbitals in the supercell.

        :return: (num_orb_sc, 3) float64 array
            Cartesian coordinates of orbitals in the supercell in nm
        """
        self.sync_array()
        orb_pos = core.build_orb_pos(self.pc_lat_vec, self.pc_orb_pos,
                                     self.orb_id_pc)
        orb_pos += self.pc_origin
        if self.orb_pos_modifier is not None:
            self.orb_pos_modifier(orb_pos)
        return orb_pos

    def _init_hop(self, with_dr: bool = False,
                  orb_pos: np.ndarray = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Get initial hopping terms and distances using the general algorithm.

        :param with_dr: whether to build initial hopping distances
        :param orb_pos: (num_orb_sc, 3) float64 array
            Cartesian coordinates of orbitals in NM
        :return: (hop_i, hop_j, hop_v, dr)
            initial hopping terms and distances (optional)
        :raises ValueError: if with_dr is True but orbital positions are not
            specified
        """
        if with_dr and orb_pos is None:
            raise ValueError("Orbital positions not specified")
        if with_dr:
            hop_i, hop_j, hop_v, dr = \
                core.build_hop(self.pc_hop_ind, self.pc_hop_eng,
                               self.dim, self.pbc, self.num_orb_pc,
                               self.orb_id_pc, self.vac_id_sc,
                               self.sc_lat_vec, orb_pos,
                               data_kind=1)
        else:
            hop_i, hop_j, hop_v =  \
                core.build_hop(self.pc_hop_ind, self.pc_hop_eng,
                               self.dim, self.pbc, self.num_orb_pc,
                               self.orb_id_pc, self.vac_id_sc,
                               self.sc_lat_vec, None,
                               data_kind=0)
            dr = None
        return hop_i, hop_j, hop_v, dr

    def _init_hop_fast(self, with_dr: bool = False,
                       orb_pos: np.ndarray = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Get initial hopping terms and distance using the fast algorithm.

        NOTE: this algorithm works only for supercells without vacancies.

        TODO: parallelize this method with MPI.

        :param with_dr: whether to build initial hopping distances
        :param orb_pos: (num_orb_sc, 3) float64 array
            Cartesian coordinates of orbitals in NM
        :return: (hop_i, hop_j, hop_v, dr)
            initial hopping terms and distances (optional)
        :raises ValueError: if with_dr is True but orbital positions are not
            specified
        """
        if with_dr and orb_pos is None:
            raise ValueError("Orbital positions not specified")

        # Split pc hopping terms into free and periodic parts
        ind_pbc, eng_pbc, ind_free, eng_free = \
            core.split_pc_hop(self.pc_hop_ind, self.pc_hop_eng, self.pbc)

        # Build sc hopping terms from periodic parts
        # This is fast since we can predict the number of hopping terms.
        if with_dr:
            i_pbc, j_pbc, v_pbc, dr_pbc = \
                core.build_hop_pbc(ind_pbc, eng_pbc,
                                   self.dim, self.pbc, self.num_orb_pc,
                                   self.sc_lat_vec, orb_pos,
                                   data_kind=1)
        else:
            i_pbc, j_pbc, v_pbc = \
                core.build_hop_pbc(ind_pbc, eng_pbc,
                                   self.dim, self.pbc, self.num_orb_pc,
                                   self.sc_lat_vec, None,
                                   data_kind=0)
            dr_pbc = None

        # Build hopping terms from free parts
        # Here we must call the general Cython function as we cannot predict
        # the number of hopping terms.
        if with_dr:
            i_free, j_free, v_free, dr_free = \
                core.build_hop(ind_free, eng_free,
                               self.dim, self.pbc, self.num_orb_pc,
                               self.orb_id_pc, self.vac_id_sc,
                               self.sc_lat_vec, orb_pos,
                               data_kind=1)
        else:
            i_free, j_free, v_free =  \
                core.build_hop(ind_free, eng_free,
                               self.dim, self.pbc, self.num_orb_pc,
                               self.orb_id_pc, self.vac_id_sc,
                               self.sc_lat_vec, None,
                               data_kind=0)
            dr_free = None

        # Assemble hopping terms and distances
        hop_i = np.append(i_pbc, i_free)
        hop_j = np.append(j_pbc, j_free)
        hop_v = np.append(v_pbc, v_free)
        if with_dr:
            dr = np.vstack((dr_pbc, dr_free))
        else:
            dr = None
        return hop_i, hop_j, hop_v, dr

    def get_hop(self, use_fast: str = "auto") -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Get indices and energies of all hopping terms in the supercell.

        NOTE: The hopping terms will be reduced by conjugate relation.
        So only half of them will be returned as results.

        :param use_fast: whether to enable the fast algorithm to build the
            hopping terms
        :return: (hop_i, hop_j, hop_v)
            hop_i: (num_hop_sc,) int64 array
            row indices of hopping terms reduced by conjugate relation
            hop_j: (num_hop_sc,) int64 array
            column indices of hopping terms reduced by conjugate relation
            hop_v: (num_hop_sc,) complex128 array
            energies of hopping terms in accordance with hop_i and hop_j in eV
        """
        self.sync_array()

        # Get initial hopping terms
        if use_fast == "auto":
            use_fast = (len(self.vacancy_list) == 0)
        if use_fast:
            hop_i, hop_j, hop_v = self._init_hop_fast()[:3]
        else:
            hop_i, hop_j, hop_v = self._init_hop()[:3]

        # Apply hopping modifier
        if self.hop_modifier.num_hop != 0:
            hop_ind, hop_eng = self.hop_modifier.to_array(use_int64=True)
            hop_i_new, hop_j_new, hop_v_new = [], [], []

            for ih in range(hop_ind.shape[0]):
                id_bra = hop_ind.item(ih, 3)
                id_ket = hop_ind.item(ih, 4)
                hop_energy = hop_eng.item(ih)
                id_same, id_conj = \
                    core.find_equiv_hopping(hop_i, hop_j, id_bra, id_ket)
                if id_same != -1:
                    hop_v[id_same] = hop_energy
                elif id_conj != -1:
                    hop_v[id_conj] = hop_energy.conjugate()
                else:
                    hop_i_new.append(id_bra)
                    hop_j_new.append(id_ket)
                    hop_v_new.append(hop_energy)

            # Append additional hopping terms
            hop_i = np.append(hop_i, hop_i_new)
            hop_j = np.append(hop_j, hop_j_new)
            hop_v = np.append(hop_v, hop_v_new)
        return hop_i, hop_j, hop_v

    def get_dr(self, use_fast: str = "auto") -> np.ndarray:
        """
        Get distances of all hopping terms in the supercell.

        NOTE: The hopping distances will be reduced by conjugate relation.
        So only half of them will be returned as results.

        NOTE: If periodic conditions are enabled, orbital indices in hop_j may
        be wrapped back if it falls out of the supercell. Nevertheless, the
        distances in dr are still the ones before wrapping. This is essential
        for adding magnetic field, calculating band structure and many
        properties involving dx and dy.

        :param use_fast: whether to enable the fast algorithm to build the
            hopping distances
        :return: dr: (num_hop_sc, 3) float64 array
            distances of hopping terms in accordance with hop_i and hop_j in nm
        """
        self.sync_array()
        orb_pos = self.get_orb_pos()

        # Get initial hopping terms and dr
        if use_fast == "auto":
            use_fast = (len(self.vacancy_list) == 0)
        if use_fast:
            hop_i, hop_j, hop_v, dr = self._init_hop_fast(with_dr=True,
                                                          orb_pos=orb_pos)
        else:
            hop_i, hop_j, hop_v, dr = self._init_hop(with_dr=True,
                                                     orb_pos=orb_pos)

        # Apply hopping modifier
        if self.hop_modifier.num_hop != 0:
            hop_ind, hop_eng = self.hop_modifier.to_array(use_int64=True)
            dr_new = []

            for ih in range(hop_ind.shape[0]):
                id_bra = hop_ind.item(ih, 3)
                id_ket = hop_ind.item(ih, 4)
                rn = np.matmul(hop_ind[ih, :3], self.sc_lat_vec)
                dr_i = orb_pos[id_ket] + rn - orb_pos[id_bra]
                id_same, id_conj = \
                    core.find_equiv_hopping(hop_i, hop_j, id_bra, id_ket)
                if id_same != -1:
                    dr[id_same] = dr_i
                elif id_conj != -1:
                    dr[id_conj] = -dr_i
                else:
                    dr_new.append(dr_i)

            # Append additional hopping distances
            if len(dr_new) != 0:
                dr = np.vstack((dr, dr_new))
        return dr

    def trim(self) -> None:
        """
        Trim dangling orbitals and associated hopping terms.

        :return: None.
        :raises SCLockError: if the object is locked
        """
        if self.is_locked:
            raise exc.SCLockError()

        # Get indices of dangling orbitals
        hop_i, hop_j, hop_v = self.get_hop()
        id_pc_trim = core.get_orb_id_trim(self.orb_id_pc, hop_i, hop_j)
        id_sc_trim = self.orb_id_pc2sc_array(id_pc_trim)

        # Add vacancies
        self.add_vacancies(id_pc_trim)

        # Also trim hop_modifier
        self.hop_modifier.remove_orbitals(id_sc_trim)

    def get_reciprocal_vectors(self) -> np.ndarray:
        """
        Get the Cartesian coordinates of reciprocal lattice vectors in 1/NM.

        :return: (3, 3) float64 array
            reciprocal vectors in 1/NM
        """
        return lat.gen_reciprocal_vectors(self.sc_lat_vec)

    def get_lattice_area(self, direction: str = "c") -> float:
        """
        Get the area formed by lattice vectors normal to given direction.

        :param direction: direction of area, e.g. "c" indicates the area formed
            by lattice vectors in the aOb plane.
        :return: area formed by lattice vectors in NM^2
        """
        return lat.get_lattice_area(self.sc_lat_vec, direction)

    def get_lattice_volume(self) -> float:
        """
        Get the volume formed by all three lattice vectors in NM^3.

        :return: volume in NM^3
        """
        return lat.get_lattice_volume(self.sc_lat_vec)

    def plot(self, axes: plt.Axes,
             with_orbitals: bool = True,
             with_cells: bool = True,
             hop_as_arrows: bool = True,
             hop_eng_cutoff: float = 1e-5,
             hop_color: str = "r",
             view: str = "ab") -> None:
        """
        Plot lattice vectors, orbitals, and hopping terms to axes.

        :param axes: axes on which the figure will be plotted
        :param with_orbitals: whether to plot orbitals as filled circles
        :param with_cells: whether to plot borders of primitive cells
        :param hop_as_arrows: whether to plot hopping terms as arrows
        :param hop_eng_cutoff: cutoff for showing hopping terms
        :param hop_color: color of hopping terms
        :param view: kind of view point, should be in 'ab', 'bc', 'ca', 'ba',
            'cb', 'ac'
        :return: None
        :raises IDPCIndexError: if cell or orbital index of bra or ket in
            hop_modifier is out of range
        :raises IDPCVacError: if bra or ket in hop_modifier corresponds
            to a vacancy
        :raises ValueError: if view is illegal
        """
        viewer = ModelViewer(axes, self.pc_lat_vec, self.pc_origin, view)

        # Plot orbitals
        orb_pos = self.get_orb_pos()
        orb_eng = self.get_orb_eng()
        if with_orbitals:
            viewer.scatter(orb_pos, c=orb_eng)

        # Plot hopping terms
        hop_i, hop_j, hop_v = self.get_hop()
        dr = self.get_dr()
        for i_h in range(hop_i.shape[0]):
            if abs(hop_v.item(i_h)) >= hop_eng_cutoff:
                pos_i = orb_pos[hop_i.item(i_h)]
                pos_j = pos_i + dr[i_h]
                if hop_as_arrows:
                    viewer.plot_arrow(pos_i, pos_j, color=hop_color,
                                      length_includes_head=True,
                                      width=0.002, head_width=0.02, fill=False)
                else:
                    viewer.add_line(pos_i, pos_j)
        if not hop_as_arrows:
            viewer.plot_line(color=hop_color)

        # Plot cells
        if with_cells:
            if view in ("ab", "ba"):
                viewer.add_grid(0, self.dim.item(0), 0, self.dim.item(1))
            elif view in ("bc", "cb"):
                viewer.add_grid(0, self.dim.item(1), 0, self.dim.item(2))
            else:
                viewer.add_grid(0, self.dim.item(0), 0, self.dim.item(2))
            viewer.plot_grid(color="k", linestyle=":")
            viewer.plot_lat_vec(color="k", length_includes_head=True,
                                width=0.005, head_width=0.02)

    @property
    def pc_lat_vec(self) -> np.ndarray:
        """
        Get the lattice vectors of primitive cell.

        :return: (3, 3) float64 array
            lattice vectors of primitive cell in nm.
        """
        return self.prim_cell.lat_vec

    @property
    def sc_lat_vec(self) -> np.ndarray:
        """
        Get the lattice vectors of supercell.

        :return: (3, 3) float64 array
            lattice vectors of primitive cell in nm.
        """
        sc_lat_vec = self.pc_lat_vec.copy()
        for i in range(3):
            sc_lat_vec[i] *= self.dim.item(i)
        return sc_lat_vec

    @property
    def pc_origin(self) -> np.ndarray:
        """
        Get the lattice origin of primitive cell.

        :return: (3,) float64 array
            lattice origin of primitive cell in NM
        """
        return self.prim_cell.origin

    @property
    def pc_orb_pos(self) -> np.ndarray:
        """
        Get the orbital positions of primitive cell.

        :return: (num_orb_pc, 3) float64 array
            fractional positions of primitive cell
        """
        self.prim_cell.sync_array()
        return self.prim_cell.orb_pos

    @property
    def pc_orb_eng(self) -> np.ndarray:
        """
        Get the energies of orbitals of primitive cell.

        :return: (num_orb_pc,) float64 array
            energies of orbitals of primitive cell in eV.
        """
        self.prim_cell.sync_array()
        return self.prim_cell.orb_eng

    @property
    def pc_hop_ind(self) -> np.ndarray:
        """
        Get the indices of hopping terms of primitive cell.

        :return: (num_hop_pc, 5) int32 array
            indices of hopping terms of primitive cell
        """
        self.prim_cell.sync_array()
        return self.prim_cell.hop_ind

    @property
    def pc_hop_eng(self) -> np.ndarray:
        """
        Get the energies of hopping terms of primitive cell.

        :return: (num_hop_pc,) complex128 array
            hopping energies of primitive cell in eV
        """
        self.prim_cell.sync_array()
        return self.prim_cell.hop_eng
