#  Author: Artem Pulkin
"""
This and other `_slow` modules implement the time-dependent Kohn-Sham procedure. The primary performance drawback is
that, unlike other 'fast' routines with an implicit construction of the eigenvalue problem, these modules construct
TDHF matrices explicitly by proxying to pyscf density response routines with a O(N^4) complexity scaling. As a result,
regular `numpy.linalg.eig` can be used to retrieve TDKS roots in a reliable fashion without any issues related to the
Davidson procedure. Several variants of TDKS are available:

 * (this module) `pyscf.tdscf.rks_slow`: the molecular implementation;
 * `pyscf.pbc.tdscf.rks_slow`: PBC (periodic boundary condition) implementation for RKS objects of `pyscf.pbc.scf`
 modules;
 * `pyscf.pbc.tdscf.krks_slow_supercell`: PBC implementation for KRKS objects of `pyscf.pbc.scf` modules. Works with
   an arbitrary number of k-points but has a overhead due to an effective construction of a supercell.
 * `pyscf.pbc.tdscf.krks_slow_gamma`: A Gamma-point calculation resembling the original `pyscf.pbc.tdscf.krks`
   module. Despite its name, it accepts KRKS objects with an arbitrary number of k-points but finds only few TDKS roots
   corresponding to collective oscillations without momentum transfer;
 * `pyscf.pbc.tdscf.krks_slow`: PBC implementation for KRKS objects of `pyscf.pbc.scf` modules. Works with
   an arbitrary number of k-points and employs k-point conservation (diagonalizes matrix blocks separately).
"""

# Convention for these modules:
# * PhysERI, PhysERI4, PhysERI8 are proxy classes for computing the full TDDFT matrix
# * vector_to_amplitudes reshapes and normalizes the solution
# * TDRKS provides a container

from pyscf.tdscf.common_slow import TDProxyMatrixBlocks, MolecularMFMixin, ab2full
from pyscf.tdscf import rhf_slow, TDDFT

import numpy


def molecular_response(vind, space, nocc, double):
    """
    Retrieves a raw response matrix.
    Args:
        vind (Callable): a pyscf matvec routine;
        space (ndarray): the active space;
        nocc (int): the number of occupied orbitals (frozen and active);
        double (bool): set to True if `vind` returns the double-sized (i.e. full) matrix;

    Returns:
        The TD matrix.
    """
    nmo_full = len(space)
    nocc_full = nocc
    nvirt_full = nmo_full - nocc_full
    size_full = nocc_full * nvirt_full

    nmo = space.sum()
    nocc = space[:nocc_full].sum()
    nvirt = nmo - nocc
    size = nocc * nvirt

    probe = numpy.zeros((size, 2 * size_full if double else size_full))

    o = space[:nocc_full]
    v = space[nocc_full:]
    ov = (o[:, numpy.newaxis] * v[numpy.newaxis, :]).reshape(-1)

    probe[numpy.arange(probe.shape[0]), numpy.argwhere(ov)[:, 0]] = 1

    if double:
        ov = numpy.tile(ov, 2)
    result = vind(probe).T[ov, :]

    if double:
        result_a = result[:size]
        result_b = result[size:]
        return ab2full(result_a, -result_b.conj())
    else:
        return result


class PhysERI(MolecularMFMixin, TDProxyMatrixBlocks):

    def __init__(self, model, frozen=None):
        """
        A proxy class for calculating the TDKS matrix blocks (molecular version).

        Args:
            model (RKS): the base model;
            frozen (int, Iterable): the number of frozen valence orbitals or the list of frozen orbitals;
        """
        TDProxyMatrixBlocks.__init__(self, TDDFT(model))
        MolecularMFMixin.__init__(self, model, frozen=frozen)

    def __get_mo_energies__(self, *args, **kwargs):
        return self.mo_energy[:self.nocc], self.mo_energy[self.nocc:]

    def get_response(self):
        """
        Retrieves a raw TD response matrix.

        Returns:
            The matrix.
        """
        nmo_full = self.nmo_full
        nocc_full = self.nocc_full
        nvirt_full = nmo_full - nocc_full
        size_full = nocc_full * nvirt_full

        if len(self.proxy_diag) == size_full:
            double = False
        elif len(self.proxy_diag) == 2 * size_full:
            double = True
        else:
            raise RuntimeError("The underlying TD* matvec routine returns arrays of unexpected size: {:d} vs "
                               "{:d} or {:d} (expected)".format(len(self.proxy_diag), size_full, 2 * size_full))

        return molecular_response(self.proxy_vind, self.space, nocc_full, double)


vector_to_amplitudes = rhf_slow.vector_to_amplitudes


class TDRKS(rhf_slow.TDRHF):
    eri1 = PhysERI
    eri4 = eri8 = None

    def __init__(self, mf, frozen=None):
        """
        Performs TDKS calculation. Roots and eigenvectors are stored in `self.e`, `self.xy`.
        Args:
            mf (RKS): the base restricted DFT model;
            frozen (int, Iterable): the number of frozen valence orbitals or the list of frozen orbitals;
        """
        super(TDRKS, self).__init__(mf, frozen=frozen)
        self.fast = True
