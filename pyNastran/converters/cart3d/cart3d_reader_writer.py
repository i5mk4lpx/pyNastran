"""
Defines:
  - Cart3D(log=None, debug=False)
     - read_cart3d(self, infilename, result_names=None)
     - write_cart3d(self, outfilename, is_binary=False, float_fmt='%6.7f')

     - flip_model()
     - make_mirror_model(self, nodes, elements, regions, loads, axis='y', tol=0.000001)
     - make_half_model(self, axis='y', remap_nodes=True)
     - get_free_edges(self, elements)
     - get_area(self)
     - get_normals(self)
     - get_normals_at_nodes(self, cnormals)

  - comp2tri(in_filenames, out_filename,
             is_binary=False, float_fmt='%6.7f')

"""
import sys
from struct import pack, unpack
from math import ceil
#from collections import defaultdict
#from typing import Union

import numpy as np
from cpylog import get_logger2
from pyNastran.utils import _filename

#from pyNastran.utils import is_binary_file, _filename

class Cart3dReaderWriter:
    """
    Cart3d IO class
    """
    def __init__(self, log=None, debug=False):
        self.log = get_logger2(log, debug=debug)
        self._endian = b''
        self._encoding = 'latin1'
        self.n = 0
        self.infile = None
        self.infilename = None
        self.points = np.zeros((0, 3), dtype='float64')
        self.elements = np.zeros((0, 3), dtype='int32')
        self.regions = np.zeros(0, dtype='int32')
        self.loads = {}

    def _write_header(self, outfile, points, elements, is_loads, is_binary=False):
        """
        writes the cart3d header

        Without results
        ---------------
        npoints nelements

        With results
        ------------
        npoints nelements nresults

        """
        npoints = points.shape[0]
        nelements = elements.shape[0]

        if is_binary:
            if is_loads:
                fmt = self._endian + b'iiiii'
                msg = pack(fmt, 3*4, npoints, nelements, 6, 4)
            else:
                fmt = self._endian + b'iiii'
                msg = pack(fmt, 2*4, npoints, nelements, 4)

            int_fmt = None
        else:
            # this is ASCII data
            if is_loads:
                msg = '%i %i 6\n' % (npoints, nelements)
            else:
                msg = '%i %i\n' % (npoints, nelements)

            # take the max value, string it, and length it
            # so 123,456 is length 6
            int_fmt = '%%%si' % len(str(nelements))
        outfile.write(msg)
        return int_fmt

    def _write_points(self, outfile, points, is_binary, float_fmt='%6.6f'):
        """writes the points"""
        if is_binary:
            four = pack(self._endian + b'i', 4)
            outfile.write(four)

            npoints = points.shape[0]
            fmt = self._endian + b'%if' % (npoints * 3)
            floats = pack(fmt, *np.ravel(points))

            outfile.write(floats)
            outfile.write(four)
        else:
            if isinstance(float_fmt, bytes):
                fmt_ascii = float_fmt
            else:
                fmt_ascii = float_fmt.encode('latin1')
            np.savetxt(outfile, points, fmt_ascii)

    def _write_elements(self, outfile, elements, is_binary, int_fmt='%6i'):
        """writes the triangles"""
        min_e = elements.min()
        assert min_e >= 0, 'min(elements)=%s' % min_e
        if is_binary:
            fmt = self._endian + b'i'
            four = pack(fmt, 4)
            outfile.write(four)
            nelements = elements.shape[0]
            fmt = self._endian + b'%ii' % (nelements * 3)
            ints = pack(fmt, *np.ravel(elements+1))

            outfile.write(ints)
            outfile.write(four)
        else:
            if isinstance(int_fmt, bytes):
                fmt_ascii = int_fmt
            else:
                fmt_ascii = int_fmt.encode('latin1')
            np.savetxt(outfile, elements+1, fmt_ascii)

    def _write_regions(self, outfile, regions, is_binary):
        """writes the regions"""
        if is_binary:
            fmt = self._endian + b'i'
            four = pack(fmt, 4)
            outfile.write(four)

            nregions = len(regions)
            fmt = self._endian + b'%ii' % nregions
            ints = pack(fmt, *regions)
            outfile.write(ints)

            outfile.write(four)
        else:
            fmt = b'%i'
            np.savetxt(outfile, regions, fmt)

    def _write_loads(self, outfile, loads, is_binary, float_fmt='%6.6f'):
        """writes the *.triq loads"""
        if is_binary:
            raise NotImplementedError('is_binary=%s' % is_binary)
        else:
            Cp = loads['Cp']
            rho = loads['rho']
            rhoU = loads['rhoU']
            rhoV = loads['rhoV']
            rhoW = loads['rhoW']
            E = loads['E']
            npoints = self.points.shape[0]
            assert len(Cp) == npoints, 'len(Cp)=%s npoints=%s' % (len(Cp), npoints)
            #nrows = len(Cp)
            fmt = '%s\n%s %s %s %s %s\n' % (float_fmt, float_fmt, float_fmt,
                                            float_fmt, float_fmt, float_fmt)
            for (cpi, rhoi, rhou, rhov, rhoe, e) in zip(Cp, rho, rhoU, rhoV, rhoW, E):
                outfile.write(fmt % (cpi, rhoi, rhou, rhov, rhoe, e))

    def _read_header_ascii(self, infile):
        """
        Reads the header::

          npoints nelements          # geometry
          npoints nelements nresults # results

        """
        line = infile.readline()
        sline = line.strip().split()
        if len(sline) == 2:
            npoints, nelements = int(sline[0]), int(sline[1])
            nresults = 0
        elif len(sline) == 3:
            npoints = int(sline[0])
            nelements = int(sline[1])
            nresults = int(sline[2])
        else:
            raise ValueError('invalid result type')
        return npoints, nelements, nresults

    @property
    def nresults(self) -> int:
        """get the number of results"""
        if isinstance(self.loads, dict):
            return len(self.loads)
        return 0

    @property
    def nnodes(self) -> int:
        """alternate way to access number of points"""
        return self.npoints

    @property
    def npoints(self) -> int:
        """get the number of points"""
        return self.points.shape[0]

    @property
    def nodes(self) -> np.ndarray:
        """alternate way to access the points"""
        return self.points

    @nodes.setter
    def nodes(self, points) -> None:
        """alternate way to access the points"""
        self.points = points

    @property
    def nelements(self) -> int:
        """get the number of elements"""
        return self.elements.shape[0]

    def _read_points_ascii(self, infile, npoints: int) -> np.ndarray:
        """
        A point is defined by x,y,z and the ID is the location in points.

        """
        p = 0
        data = []
        assert npoints > 0, 'npoints=%s' % npoints
        points = np.zeros((npoints, 3), dtype='float32')
        while p < npoints:
            data += infile.readline().strip().split()
            while len(data) > 2:
                x = data.pop(0)
                y = data.pop(0)
                z = data.pop(0)
                points[p] = [x, y, z]
                p += 1
        return points

    def _read_elements_ascii(self, infile, nelements: int) -> np.ndarray:
        """
        An element is defined by n1,n2,n3 and the ID is the location in elements.

        """
        assert nelements > 0, 'npoints=%s nelements=%s' % (self.npoints, nelements)
        elements = np.zeros((nelements, 3), dtype='int32')

        ieid = 0
        data = []
        while ieid < nelements:
            data += infile.readline().strip().split()
            while len(data) > 2:
                n1 = int(data.pop(0))
                n2 = int(data.pop(0))
                n3 = int(data.pop(0))
                elements[ieid] = [n1, n2, n3]
                ieid += 1

        nid_min = elements.min()
        if nid_min != 1:
            nid_max = elements.max()
            nnodes = self.nodes.shape[0]
            if nid_max == nnodes:
                msg = (
                    'Possible Cart3d error due to unused nodes\n'
                    'min(nids)=%s; expected 1; nid_max=%s nnodes=%s' % (
                        nid_min, nid_max, nnodes))
                self.log.warning(msg)
            else:
                msg = 'elements:\n%s\nmin(nids)=%s; expected 1; nid_max=%s nnodes=%s' % (
                    elements, nid_min, nid_max, nnodes, )
                #raise RuntimeError(msg)
                self.log.warning(msg)
            #assert elements.min() == 1, elements.min()
        return elements - 1

    def _read_regions_ascii(self, infile, nelements: int) -> np.ndarray:
        """reads the region section"""
        regions = np.zeros(nelements, dtype='int32')
        iregion = 0
        data = []
        while iregion < nelements:
            data = infile.readline().strip().split()
            ndata = len(data)
            regions[iregion : iregion + ndata] = data
            iregion += ndata
        return regions

    def _read_results_ascii(self, i, infile, nresults, result_names=None):
        """
        Reads the Cp results.
        Results are read on a nodal basis from the following table:
          Cp
          rho,rhoU,rhoV,rhoW,rhoE

        With the following definitions:
          Cp = (p - 1/gamma) / (0.5*M_inf*M_inf)
          rhoVel^2 = rhoU^2+rhoV^2+rhoW^2
          M^2 = rhoVel^2/rho^2

        Thus:
          p = (gamma-1)*(e- (rhoU**2+rhoV**2+rhoW**2)/(2.*rho))
          p_dimensional = qInf * Cp + pInf

        # ???
        rho,rhoU,rhoV,rhoW,rhoE

        Parameters
        ----------
        result_names : List[str]; default=None (All)
            result_names = ['Cp', 'rho', 'rhoU', 'rhoV', 'rhoW', 'rhoE',
                            'Mach', 'U', 'V', 'W', 'E']

        """
        if nresults == 0:
            return None, []
        if result_names is None:
            result_names = ['Cp', 'rho', 'rhoU', 'rhoV', 'rhoW', 'rhoE',
                            'Mach', 'U', 'V', 'W', 'E', 'a', 'T', 'Pressure', 'q']
        self.log.debug('---starting read_results---')

        results = np.zeros((self.npoints, 6), dtype='float32')

        nresult_lines = int(ceil(nresults / 5.)) - 1
        for ipoint in range(self.npoints):
            # rho rhoU,rhoV,rhoW,pressure/rhoE/E
            sline = infile.readline().strip().split()
            i += 1
            for unused_n in range(nresult_lines):
                sline += infile.readline().strip().split()  # Cp
                i += 1
                #gamma = 1.4
                #else:
                #    p=0.
            sline = _get_list(sline)

            # Cp
            # rho       rhoU      rhoV      rhoW      E
            # 0.416594
            # 1.095611  0.435676  0.003920  0.011579  0.856058
            results[ipoint, :] = sline

            #p=0
            #cp = sline[0]
            #rho = float(sline[1])
            #if(rho > abs(0.000001)):
                #rhoU = float(sline[2])
                #rhoV = float(sline[3])
                #rhoW = float(sline[4])
                #rhoE = float(sline[5])
                #mach2 = (rhoU) ** 2 + (rhoV) ** 2 + (rhoW) ** 2 / rho ** 2
                #mach = sqrt(mach2)
                #if mach > 10:
                    #print("nid=%s Cp=%s mach=%s rho=%s rhoU=%s rhoV=%s rhoW=%s" % (
                        #pointNum, cp, mach, rho, rhoU, rhoV, rhoW))
            #print("pt=%s i=%s Cp=%s p=%s" %(pointNum,i,sline[0],p))
        del sline
        return results, result_names

    def _read_cart3d_ascii(self, cart3d_filename: str, encoding: str, result_names):
        with open(_filename(cart3d_filename), 'r', encoding=self._encoding) as infile:
            try:
                npoints, nelements, nresults = self._read_header_ascii(infile)
                self.points = self._read_points_ascii(infile, npoints)
                self.elements = self._read_elements_ascii(infile, nelements)
                self.regions = self._read_regions_ascii(infile, nelements)
                results, result_names = self._read_results_ascii(0, infile, nresults,
                                                                 result_names=result_names)
                if results is not None:
                    self.loads = self._calculate_results(result_names, results)
            except Exception:
                msg = f'failed reading {cart3d_filename!r}'
                self.log.error(msg)
                raise

    def _read_cart3d_binary(self, cart3d_filename: str, endian: bytes):
        with open(cart3d_filename, 'rb') as infile:
            self.infile = infile
            try:
                npoints, nelements, nresults = self._read_header_binary(infile)
                self.points = self._read_points_binary(infile, npoints)
                self.elements = self._read_elements_binary(infile, nelements)
                self.regions = self._read_regions_binary(infile, nelements)
                # TODO: loads
            except Exception:
                msg = f'failed reading {cart3d_filename!r}'
                self.log.error(msg)
                raise

    def _read_header_binary(self, infile):
        """
        Reads the header::

          npoints nelements          # geometry
          npoints nelements nresults # results

        """
        data = self.infile.read(4)
        size_little, = unpack(b'<i', data)
        size_big, = unpack(b'>i', data)
        if size_big in [12, 8]:
            self._endian = b'>'
            size = size_big
        elif size_little in [8, 12]:
            self._endian = b'<'
            size = size_little
        else:
            self._rewind()
            self.show(100)
            raise RuntimeError('unknown endian')

        self.n += 4
        data = self.infile.read(size)
        self.n += size

        so4 = size // 4  # size over 4
        if so4 == 3:
            (npoints, nelements, nresults) = unpack(self._endian + b'iii', data)
            self.log.info("npoints=%s nelements=%s nresults=%s" % (npoints, nelements, nresults))
        elif so4 == 2:
            (npoints, nelements) = unpack(self._endian + b'ii', data)
            nresults = 0
            self.log.info("npoints=%s nelements=%s" % (npoints, nelements))
        else:
            self._rewind()
            self.show(100)
            raise RuntimeError('in the wrong spot...endian...size/4=%s' % so4)
        self.infile.read(8)  # end of first block, start of second block
        return (npoints, nelements, nresults)

    def _read_points_binary(self, infile, npoints: int) -> np.ndarray:
        """reads the xyz points"""
        size = npoints * 12  # 12=3*4 all the points
        data = infile.read(size)

        dtype = np.dtype(self._endian + b'f4')
        points = np.frombuffer(data, dtype=dtype).reshape((npoints, 3)).copy()

        infile.read(8)  # end of second block, start of third block
        return points

    def _read_elements_binary(self, infile, nelements: int) -> np.ndarray:
        """reads the triangles"""
        size = nelements * 12  # 12=3*4 all the elements
        data = infile.read(size)

        dtype = np.dtype(self._endian + b'i4')
        elements = np.frombuffer(data, dtype=dtype).reshape((nelements, 3)).copy()

        infile.read(8)  # end of third (element) block, start of regions (fourth) block
        assert elements.min() == 1, elements.min()
        return elements - 1

    def _read_regions_binary(self, infile, nelements: int) -> np.ndarray:
        """reads the regions"""
        size = nelements * 4  # 12=3*4 all the elements
        data = infile.read(size)

        regions = np.zeros(nelements, dtype='int32')
        dtype = self._endian + b'i'
        regions = np.frombuffer(data, dtype=dtype).copy()

        infile.read(4)  # end of regions (fourth) block
        return regions

    def _read_results_binary(self, i: int, infile, result_names=None):
        """binary results are not supported"""
        pass

    def _rewind(self):  # pragma: no cover
        """go back to the beginning of the file"""
        self.n = 0
        self.infile.seek(self.n)

    def show(self, n, types='ifs', endian=None):  # pragma: no cover
        assert self.n == self.infile.tell(), 'n=%s tell=%s' % (self.n, self.infile.tell())
        #nints = n // 4
        data = self.infile.read(4 * n)
        strings, ints, floats = self.show_data(data, types=types, endian=endian)
        self.infile.seek(self.n)
        return strings, ints, floats

    def show_data(self, data, types='ifs', endian=None):  # pragma: no cover
        return self._write_data(sys.stdout, data, types=types, endian=endian)

    def _write_data(self, outfile, data, types='ifs', endian=None):  # pragma: no cover
        """Useful function for seeing what's going on locally when debugging."""
        n = len(data)
        nints = n // 4
        ndoubles = n // 8
        strings = None
        ints = None
        floats = None
        longs = None

        if endian is None:
            endian = self._endian

        if 's' in types:
            strings = unpack('%s%is' % (endian, n), data)
            outfile.write("strings = %s\n" % str(strings))
        if 'i' in types:
            ints = unpack('%s%ii' % (endian, nints), data)
            outfile.write("ints    = %s\n" % str(ints))
        if 'f' in types:
            floats = unpack('%s%if' % (endian, nints), data)
            outfile.write("floats  = %s\n" % str(floats))

        if 'l' in types:
            longs = unpack('%s%il' % (endian, nints), data)
            outfile.write("long  = %s\n" % str(longs))
        if 'I' in types:
            ints2 = unpack('%s%iI' % (endian, nints), data)
            outfile.write("unsigned int = %s\n" % str(ints2))
        if 'L' in types:
            longs2 = unpack('%s%iL' % (endian, nints), data)
            outfile.write("unsigned long = %s\n" % str(longs2))
        if 'q' in types:
            longs = unpack('%s%iq' % (endian, ndoubles), data[:ndoubles*8])
            outfile.write("long long = %s\n" % str(longs))
        return strings, ints, floats

    def show_ndata(self, n, types='ifs'):  # pragma: no cover
        return self._write_ndata(sys.stdout, n, types=types)

    def _write_ndata(self, outfile, n, types='ifs'):  # pragma: no cover
        """Useful function for seeing what's going on locally when debugging."""
        nold = self.n
        data = self.infile.read(n)
        self.n = nold
        self.infile.seek(self.n)
        return self._write_data(outfile, data, types=types)


def convert_to_float(svalues: list[str]) -> list[float]:
    """Takes a list of strings and converts them to floats."""
    values = []
    for value in svalues:
        values.append(float(value))
    return values

def _get_list(sline: list[str]) -> list[float]:
    """Takes a list of strings and converts them to floats."""
    try:
        sline2 = convert_to_float(sline)
    except ValueError:
        print("sline = %s" % sline)
        raise SyntaxError('cannot parse %s' % sline)
    return sline2

def b(mystr: str) -> bytes:
    """reimplementation of six.b(...) to work in Python 2"""
    return mystr.encode('ascii')