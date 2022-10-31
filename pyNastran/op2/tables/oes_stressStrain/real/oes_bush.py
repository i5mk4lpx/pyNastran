import numpy as np
from numpy import zeros

from pyNastran.utils.numpy_utils import integer_types
from pyNastran.op2.result_objects.op2_objects import get_times_dtype
from pyNastran.op2.tables.oes_stressStrain.real.oes_objects import StressObject, StrainObject, OES_Object
from pyNastran.f06.f06_formatting import write_floats_13e, _eigenvalue_header


class RealBushArray(OES_Object):
    def __init__(self, data_code, is_sort1, isubcase, dt):
        OES_Object.__init__(self, data_code, isubcase, apply_data_code=False)
        #self.code = [self.format_code, self.sort_code, self.s_code]
        #self.ntimes = 0  # or frequency/mode
        #self.ntotal = 0
        self.ielement = 0
        self.nelements = 0  # result specific
        #print('RealBushArray.nonlinear_factor =', self.nonlinear_factor)

    @property
    def is_real(self) -> bool:
        return True

    @property
    def is_complex(self) -> bool:
        return False

    @property
    def nnodes_per_element(self) -> int:
        return 1

    def _reset_indices(self) -> None:
        self.itotal = 0
        if self.table_name not in ['OESRMS2', 'OESNO2', 'OSTRRMS2', 'OSTRNO2']:
            self.ielement = 0

    def _get_msgs(self):
        raise NotImplementedError('%s needs to implement _get_msgs' % self.__class__.__name__)

    def get_headers(self):
        raise NotImplementedError('%s needs to implement get_headers' % self.__class__.__name__)
        #return headers

    def build(self):
        """sizes the vectorized attributes of the RealBushArray"""
        #print('ntimes=%s nelements=%s ntotal=%s' % (self.ntimes, self.nelements, self.ntotal))
        if self.is_built:
            return
        assert self.ntimes > 0, 'ntimes=%s' % self.ntimes
        assert self.nelements > 0, 'nelements=%s' % self.nelements
        assert self.ntotal > 0, 'ntotal=%s' % self.ntotal

        assert self.element_type == 102, self.element_type
        #nnodes_per_element = 1

        self.itime = 0
        self.ielement = 0
        self.itotal = 0
        #self.ntimes = 0
        #self.nelements = 0

        #print("***name=%s type=%s nnodes_per_element=%s ntimes=%s nelements=%s ntotal=%s" % (
            #self.element_name, self.element_type, nnodes_per_element, self.ntimes, self.nelements, self.ntotal))
        dtype, idtype, fdtype = get_times_dtype(self.nonlinear_factor, self.size, self.analysis_fmt)

        # [tx, ty, tz, rx, ry, rz]
        if self.is_sort1:
            ntimes = self.ntimes
            ntotal = self.ntotal
        else:
            ntimes = self.ntotal
            ntotal = self.ntimes
            #print('BUSH SORT2:', ntimes, ntotal)

        # buggy MSC 2005 (was this ever fixed?)
        # NX doesn't have this bug
        if self.table_name in ['OESRMS2', 'OESNO2', 'OSTRRMS2', 'OSTRNO2']:
            print('flipping the order...')
            ntimes, ntotal = ntotal, ntimes

        _times = zeros(ntimes, dtype=dtype)
        element = zeros(ntotal, dtype=idtype)
        data = zeros((ntimes, ntotal, 6), dtype=fdtype)

        if self.load_as_h5:
            #for key, value in sorted(self.data_code.items()):
                #print(key, value)
            group = self._get_result_group()
            self._times = group.create_dataset('_times', data=_times)
            self.element = group.create_dataset('element', data=element)
            self.data = group.create_dataset('data', data=data)
        else:
            self._times = _times
            self.element = element
            self.data = data

    def build_dataframe(self):
        """creates a pandas dataframe"""
        import pandas as pd
        headers = self.get_headers()
        if self.nonlinear_factor not in (None, np.nan):
            #Time           0.00 0.10
            #ElementID Item
            #11        tx    0.0  0.0
            #          ty    0.0  0.0
            #          tz    0.0  0.0
            #          rx    0.0  0.0
            #          ry    0.0  0.0
            #          rz    0.0  0.0
            #21        tx    0.0  0.0
            column_names, column_values = self._build_dataframe_transient_header()
            data_frame = self._build_pandas_transient_elements(
                column_values, column_names,
                headers, self.element, self.data)
        else:
            # >25.0
            #Static         tx   ty   tz   rx   ry   rz
            #ElementID
            #1          1000.0  0.0  0.0  0.0  0.0  0.0
            #
            # <=24.2
            #Static               0
            #ElementID Item
            #1         tx    1000.0
            #          ty       0.0
            #          tz       0.0
            #          rx       0.0
            #          ry       0.0
            #          rz       0.0
            data_frame = pd.DataFrame(self.data[0], columns=headers, index=self.element)
            data_frame.index.name = 'ElementID'
            data_frame.columns.names = ['Static']
            #data_frame = pd.Panel(self.data, major_axis=self.element, minor_axis=headers).to_frame()
            #data_frame.columns.names = ['Static']
            #data_frame.index.names = ['ElementID', 'Item']
        self.data_frame = data_frame

    def __eq__(self, table):  # pragma: no cover
        assert self.is_sort1 == table.is_sort1
        self._eq_header(table)
        if not np.array_equal(self.data, table.data):
            msg = 'table_name=%r class_name=%s\n' % (self.table_name, self.__class__.__name__)
            msg += '%s\n' % str(self.code_information())
            ntimes = self.data.shape[0]

            i = 0
            if self.is_sort1:
                for itime in range(ntimes):
                    for ieid, eid, in enumerate(self.element):
                        t1 = self.data[itime, ieid, :]
                        t2 = table.data[itime, ieid, :]
                        (fx1, fy1, fz1, unused_mx1, unused_my1, unused_mz1) = t1
                        (fx2, fy2, fz2, unused_mx2, unused_my2, unused_mz2) = t2
                        if not np.allclose(t1, t2):
                        #if not np.array_equal(t1, t2):
                            msg += '%s\n  (%s, %s, %s)\n  (%s, %s, %s)\n' % (
                                eid,
                                fx1, fy1, fz1,  #mx1, my1, mz1
                                fx2, fy2, fz2)  #mx2, my2, mz2
                            i += 1
                        if i > 10:
                            print(msg)
                            raise ValueError(msg)
            else:
                raise NotImplementedError(self.is_sort2)
            if i > 0:
                print(msg)
                raise ValueError(msg)
        return True

    def add_sort1(self, dt, eid, tx, ty, tz, rx, ry, rz):
        """unvectorized method for adding SORT1 transient data"""
        assert isinstance(eid, integer_types) and eid > 0, 'dt=%s eid=%s' % (dt, eid)
        self._times[self.itime] = dt
        self.element[self.itotal] = eid
        self.data[self.itime, self.itotal, :] = [tx, ty, tz, rx, ry, rz]
        self.itotal += 1
        self.ielement += 1

    def add_sort2(self, dt, eid, tx, ty, tz, rx, ry, rz):
        """unvectorized method for adding SORT1 transient data"""
        assert isinstance(eid, integer_types) and eid > 0, 'dt=%s eid=%s' % (dt, eid)
        itime = self.ielement
        itotal = self.itime
        #print(f'dt={dt} eid={eid}; itime={itime}; itotal={itotal}')
        self._times[itime] = dt
        self.element[itotal] = eid
        self.data[itime, itotal, :] = [tx, ty, tz, rx, ry, rz]
        self.itotal += 1
        self.ielement += 1

    def get_stats(self, short: bool=False) -> list[str]:
        if not self.is_built:
            return ['<%s>\n' % self.__class__.__name__,
                    f'  ntimes: {self.ntimes:d}\n',
                    f'  ntotal: {self.ntotal:d}\n',
                    ]

        nelements = self.ntotal
        ntimes = self.ntimes
        #ntotal = self.ntotal
        nelements = self.ntotal

        msg = []
        if self.nonlinear_factor not in (None, np.nan):  # transient
            msg.append('  type=%s ntimes=%i nelements=%i\n'
                       % (self.__class__.__name__, ntimes, nelements))
            ntimes_word = 'ntimes'
        else:
            msg.append('  type=%s nelements=%i\n'
                       % (self.__class__.__name__, nelements))
            ntimes_word = '1'
        headers = self.get_headers()

        n = len(headers)
        assert n == self.data.shape[2], 'nheaders=%s shape=%s' % (n, str(self.data.shape))
        msg.append('  data: [%s, ntotal, %i] where %i=[%s]\n' % (ntimes_word, n, n, str(', '.join(headers))))
        msg.append(f'  element.shape = {self.element.shape}\n')
        msg.append(f'  data.shape = {self.data.shape}\n')
        msg.append(f'  element type: {self.element_name}-{self.element_type}\n')
        msg += self.get_data_code()
        return msg

    def get_element_index(self, eids):
        # elements are always sorted; nodes are not
        itot = np.searchsorted(eids, self.element)  #[0]
        return itot

    def eid_to_element_node_index(self, eids):
        ind = np.ravel([np.searchsorted(self.element == eid) for eid in eids])
        return ind

    def write_f06(self, f06_file, header=None, page_stamp='PAGE %s',
                  page_num: int=1, is_mag_phase: bool=False, is_sort1: bool=True):
        if header is None:
            header = []
        msg = self._get_msgs()
        (ntimes, unused_ntotal) = self.data.shape[:2]
        eids = self.element

        for itime in range(ntimes):
            dt = self._times[itime]
            header = _eigenvalue_header(self, header, itime, ntimes, dt)
            f06_file.write(''.join(header + msg))
            #[tx, ty, tz, rx, ry, rz]
            tx = self.data[itime, :, 0]
            ty = self.data[itime, :, 1]
            tz = self.data[itime, :, 2]
            rx = self.data[itime, :, 3]
            ry = self.data[itime, :, 4]
            rz = self.data[itime, :, 5]

            for eid, txi, tyi, tzi, rxi, ryi, rzi in zip(
                    eids, tx, ty, tz, rx, ry, rz):
                vals = [txi, tyi, tzi, rxi, ryi, rzi]
                vals2 = write_floats_13e(vals)
                [txi, tyi, tzi, rxi, ryi, rzi] = vals2
                f06_file.write('0                   %8i     %-13s %-13s %-13s %-13s %-13s %s\n' % (
                    eid, txi, tyi, tzi, rxi, ryi, rzi))
            f06_file.write(page_stamp % page_num)
            page_num += 1
        if self.nonlinear_factor in (None, np.nan):
            page_num -= 1
        return page_num

    def write_op2(self, op2_file, op2_ascii, itable, new_result, date,
                  is_mag_phase=False, endian='>'):
        """writes an OP2"""
        import inspect
        from struct import Struct, pack
        frame = inspect.currentframe()
        call_frame = inspect.getouterframes(frame, 2)
        op2_ascii.write(f'{self.__class__.__name__}.write_op2: {call_frame[1][3]}\n')

        if itable == -1:
            self._write_table_header(op2_file, op2_ascii, date)
            itable = -3

        #if isinstance(self.nonlinear_factor, float):
            #op2_format = '%sif' % (7 * self.ntimes)
            #raise NotImplementedError()
        #else:
            #op2_format = 'i21f'
        #s = Struct(op2_format)

        eids = self.element

        # table 4 info
        #ntimes = self.data.shape[0]
        #nnodes = self.data.shape[1]
        nelements = self.data.shape[1]

        # 21 = 1 node, 3 principal, 6 components, 9 vectors, 2 p/ovm
        #ntotal = ((nnodes * 21) + 1) + (nelements * 4)

        ntotali = self.num_wide
        ntotal = ntotali * nelements

        #print('shape = %s' % str(self.data.shape))
        #assert self.ntimes == 1, self.ntimes

        #device_code = self.device_code
        op2_ascii.write(f'  ntimes = {self.ntimes}\n')

        eids_device = self.element * 10 + self.device_code

        #fmt = '%2i %6f'
        #print('ntotal=%s' % (ntotal))
        #assert ntotal == 193, ntotal

        if not self.is_sort1:
            raise NotImplementedError('SORT2')
        struct1 = Struct(endian + b'i6f')

        fdtype = self.data.dtype
        if self.size == fdtype.itemsize:
            pass
        else:
            print(f'downcasting {self.class_name}...')
            #cen_word_bytes = b'CEN/    '
            idtype = np.int32(1)
            fdtype = np.float32(1.0)

        use_numpy = True
        data_out = np.empty((nelements, 7), dtype=fdtype)
        data_out[:, 0] = eids_device.view(fdtype)

        op2_ascii.write(f'nelements={nelements:d}\n')

        for itime in range(self.ntimes):
            #print('3, %s' % itable)
            self._write_table_3(op2_file, op2_ascii, new_result, itable, itime)

            # record 4
            #print('stress itable = %s' % itable)
            itable -= 1
            #print('4, %s' % itable)
            header = [4, itable, 4,
                      4, 1, 4,
                      4, 0, 4,
                      4, ntotal, 4,
                      4 * ntotal]
            op2_file.write(pack('%ii' % len(header), *header))
            op2_ascii.write('r4 [4, 0, 4]\n')
            op2_ascii.write(f'r4 [4, {itable:d}, 4]\n')
            op2_ascii.write(f'r4 [4, {4 * ntotal:d}, 4]\n')

            if use_numpy:
                # [eid_device, txi, tyi, tzi, rxi, ryi, rzi]
                data_out[:, 1:] = self.data[itime, :, :]
                assert data_out.size == ntotal, f'data_out.shape={data_out.shape} size={data_out.size}; ntotal={ntotal}'
                op2_file.write(data_out)
            else:
                tx = self.data[itime, :, 0]
                ty = self.data[itime, :, 1]
                tz = self.data[itime, :, 2]
                rx = self.data[itime, :, 3]
                ry = self.data[itime, :, 4]
                rz = self.data[itime, :, 5]
                for eid, eid_device, txi, tyi, tzi, rxi, ryi, rzi in zip(
                        eids, eids_device, tx, ty, tz, rx, ry, rz):
                    data = [eid_device, txi, tyi, tzi, rxi, ryi, rzi]

                    vals = [txi, tyi, tzi, rxi, ryi, rzi]
                    vals2 = write_floats_13e(vals)
                    [txi, tyi, tzi, rxi, ryi, rzi] = vals2
                    op2_ascii.write('0                   %8i     %-13s %-13s %-13s %-13s %-13s %s\n' % (
                            eid, txi, tyi, tzi, rxi, ryi, rzi))
                    op2_file.write(struct1.pack(*data))

                #for eid, axiali, SMai, torsioni, SMti in zip(eids_device, axial, SMa, torsion, SMt):
                    #data = [eid, axiali, SMai, torsioni, SMti]
                    #op2_ascii.write('  eid=%s axial=%s SMa=%s torsion=%s SMt=%s\n' % tuple(data))
                    #op2_file.write(struct1.pack(*data))

            itable -= 1
            header = [4 * ntotal,]
            op2_file.write(pack('i', *header))
            op2_ascii.write('footer = %s\n' % header)
            new_result = False
        return itable


class RealBushStressArray(RealBushArray, StressObject):
    def __init__(self, data_code, is_sort1, isubcase, dt):
        RealBushArray.__init__(self, data_code, is_sort1, isubcase, dt)
        StressObject.__init__(self, data_code, isubcase)

    def get_headers(self) -> list[str]:
        headers = ['tx', 'ty', 'tz', 'rx', 'ry', 'rz']
        return headers

    def _get_msgs(self) -> list[str]:
        if self.element_type == 102:
            pass
        else:
            raise NotImplementedError(self.element_type)

        msg = [
            '                                  S T R E S S E S   I N   B U S H   E L E M E N T S        ( C B U S H )\n \n',
            '                  ELEMENT-ID        STRESS-TX     STRESS-TY     STRESS-TZ    STRESS-RX     STRESS-RY     STRESS-RZ \n',
        ]
        return msg


class RealBushStrainArray(RealBushArray, StrainObject):
    def __init__(self, data_code, is_sort1, isubcase, dt):
        RealBushArray.__init__(self, data_code, is_sort1, isubcase, dt)
        StrainObject.__init__(self, data_code, isubcase)

    def get_headers(self) -> list[str]:
        headers = ['tx', 'ty', 'tz', 'rx', 'ry', 'rz']
        return headers

    def _get_msgs(self) -> list[str]:
        if self.element_type == 102:
            pass
        else:
            raise NotImplementedError(self.element_type)

        msg = [
            '                                    S T R A I N S   I N   B U S H   E L E M E N T S        ( C B U S H )\n'
            ' \n'
            '                  ELEMENT-ID        STRAIN-TX     STRAIN-TY     STRAIN-TZ    STRAIN-RX     STRAIN-RY     STRAIN-RZ \n'
        ]
        return msg
