"""Read-only identity fixtures; no actual ioctl or privileged operation."""
import errno
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import wol_fs_identity as identity

UUID = bytes.fromhex('0123456789abcdef0123456789abcdef')
OTHER = bytes.fromhex('fedcba9876543210fedcba9876543210')


class FilesystemIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fd = os.open(temp.name, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        patch = mock.patch.object(identity.platform, 'machine', return_value='x86_64')
        patch.start()
        self.addCleanup(patch.stop)

    def sample(self, filesystem='btrfs', uuid=UUID, subvolume=256):
        def ioctl(fd, command, buf, mutate):
            self.assertEqual(fd, self.fd)
            self.assertTrue(mutate)
            if command == identity._FS_IOC_GETFSUUID:
                self.assertNotEqual(filesystem, 'btrfs')
                self.assertEqual(len(buf), 17)
                self.assertEqual(command, 0x80111500)
                buf[:] = bytes([len(uuid)]) + uuid.ljust(16, b'\0')
            elif command == identity._BTRFS_IOC_FS_INFO:
                self.assertEqual(filesystem, 'btrfs')
                self.assertEqual(command, 0x8400941f)
                self.assertEqual(len(buf), 1024)
                self.assertEqual(struct.unpack_from('=Q', buf, 48)[0], 4)
                self.assertEqual(buf[:48], bytes(48))
                self.assertEqual(buf[56:], bytes(968))
                if len(uuid) == 16:
                    buf[16:32] = uuid
                    buf[64:80] = uuid
                struct.pack_into('=Q', buf, 48, 4)
            else:
                self.assertEqual(command, 0xd0009412)
                self.assertEqual(len(buf), 4096)
                self.assertEqual(struct.unpack_from('=QQ', buf), (0, 256))
                struct.pack_into('=QQ', buf, 0, subvolume, 256)
            return 0
        with mock.patch.object(identity, '_mount',
                               return_value=(b'42', b'fixture', filesystem)), \
             mock.patch.object(identity.fcntl, 'ioctl', side_effect=ioctl) as calls:
            result = identity.identify(self.fd)
        return result, calls.call_count

    def test_btrfs_uuid_and_subvolume_and_inode(self):
        value, calls = self.sample()
        self.assertEqual(calls, 4)
        self.assertEqual(value.filesystem, 'btrfs')
        self.assertEqual(value.uuid, UUID)
        self.assertEqual(value.subvolume, 256)
        self.assertEqual(value.inode, os.fstat(self.fd).st_ino)
        self.assertNotIn(UUID.hex(), repr(value))

    def test_ext4_and_xfs_do_not_use_btrfs_ioctl(self):
        for fs in ('ext4', 'xfs'):
            with self.subTest(fs=fs):
                value, calls = self.sample(fs)
                self.assertEqual(calls, 2)
                self.assertEqual(value.filesystem, fs)
                self.assertEqual(value.uuid, UUID)
                self.assertIsNone(value.subvolume)

    def test_subvolume_identity_distinguishes_equal_inode_and_uuid(self):
        a, _ = self.sample(subvolume=256)
        b, _ = self.sample(subvolume=257)
        c, _ = self.sample(uuid=OTHER)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(a, self.sample()[0])

    def test_btrfs_uses_native_provider_not_generic_ioctl(self):
        # hydra: generic UUID ioctl returns ENOTTY on Btrfs.
        with mock.patch.object(identity, '_uuid',
                               side_effect=OSError(errno.ENOTTY, 'fixture')) as generic:
            value, calls = self.sample()
            self.assertEqual(value.uuid, UUID)
            self.assertEqual(calls, 4)
            generic.assert_not_called()

    def test_btrfs_rejects_missing_metadata_and_different_uuids(self):
        for fsid, metadata, flags, ret in (
                (UUID, UUID, 0, 0),
                (UUID, bytes(16), 4, 0),
                (bytes(16), bytes(16), 4, 0),
                (UUID, OTHER, 4, 0),
                (UUID, UUID, 5, 0),
                (UUID, UUID, 4, 1)):
            with self.subTest(flags=flags, ret=ret, equal=fsid == metadata):
                def response(fd, command, buf, mutate):
                    self.assertEqual(command, 0x8400941f)
                    buf[16:32] = fsid
                    buf[64:80] = metadata
                    struct.pack_into('=Q', buf, 48, flags)
                    return ret
                with mock.patch.object(identity, '_mount',
                                       return_value=(b'42', b'fixture', 'btrfs')), \
                     mock.patch.object(identity.fcntl, 'ioctl', side_effect=response), \
                     mock.patch.object(identity, '_uuid') as generic:
                    self.assertIsNone(identity.identify(self.fd))
                    generic.assert_not_called()

    def test_top_level_subvolume_is_valid(self):
        self.assertEqual(self.sample(subvolume=5)[0].subvolume, 5)

    def test_invalid_uuid_or_subvolume_refused(self):
        for uuid in (b'', bytes(16), bytes.fromhex('01020304')):
            with self.subTest(uuid=uuid):
                self.assertIsNone(self.sample(uuid=uuid)[0])
        for subvolume in (0, 1, 6, 255, 2**64 - 1):
            with self.subTest(subvolume=subvolume):
                self.assertIsNone(self.sample(subvolume=subvolume)[0])

    def test_unsupported_filesystem_never_attempts_ioctl(self):
        for fs in ('overlay', 'tmpfs', 'nfs', 'fuse', 'vfat'):
            value, calls = self.sample(fs)
            self.assertIsNone(value)
            self.assertEqual(calls, 0)

    def test_unsupported_abi_and_bad_descriptor_fail_closed(self):
        for machine in ('ppc64le', 'mips64', 's390x'):
            with mock.patch.object(identity.platform, 'machine', return_value=machine), \
                 mock.patch.object(identity.fcntl, 'ioctl') as ioctl:
                self.assertIsNone(identity.identify(self.fd))
                ioctl.assert_not_called()
        for fd in (False, None, -1):
            self.assertIsNone(identity.identify(fd))
        self.assertIsNone(identity.identify(10000000))

    def test_unsupported_ioctl_has_no_fallback(self):
        for code in (errno.ENOTTY, errno.EOPNOTSUPP, errno.EACCES, errno.EIO):
            with mock.patch.object(identity, '_mount',
                                   return_value=(b'42', b'fixture', 'btrfs')), \
                 mock.patch.object(identity.fcntl, 'ioctl',
                                   side_effect=OSError(code, 'private')), \
                 mock.patch.object(identity.os, 'fstatvfs',
                                   side_effect=AssertionError('no fallback')):
                self.assertIsNone(identity.identify(self.fd))

    def test_changed_uuid_or_subvolume_or_mount_refused(self):
        mount = (b'42', b'fixture', 'btrfs')
        with mock.patch.object(identity, '_mount', return_value=mount), \
             mock.patch.object(identity, '_btrfs_uuid', side_effect=[UUID, OTHER]), \
             mock.patch.object(identity, '_subvolume', return_value=256):
            self.assertIsNone(identity.identify(self.fd))
        with mock.patch.object(identity, '_mount', return_value=mount), \
             mock.patch.object(identity, '_btrfs_uuid', return_value=UUID), \
             mock.patch.object(identity, '_subvolume', side_effect=[256, 257]):
            self.assertIsNone(identity.identify(self.fd))
        with mock.patch.object(identity, '_mount',
                               side_effect=[mount, (b'43', b'changed', 'btrfs')]), \
             mock.patch.object(identity, '_btrfs_uuid', return_value=UUID), \
             mock.patch.object(identity, '_subvolume', return_value=256):
            self.assertIsNone(identity.identify(self.fd))

    def test_mount_id_parser_rejects_missing_duplicate_or_invalid(self):
        self.assertEqual(identity._mount_id(b'pos:\t0\nmnt_id:\t42\n'), b'42')
        for raw in (b'', b'mnt_id: 0', b'mnt_id: -1', b'mnt_id: 42\nmnt_id: 42',
                    b'mnt_id: 18446744073709551616', b'mnt_id: private'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    identity._mount_id(raw)

    def test_mount_record_matches_descriptor_not_path_or_device_number(self):
        a = b'41 1 0:19 / /etc rw - tmpfs tmpfs rw'
        b = b'42 1 0:19 /@ /etc/systemd rw - btrfs /dev/example rw'
        self.assertEqual(identity._mount_record(a+b'\n'+b+b'\n', b'42'), (b, 'btrfs'))
        for raw in (a, b+b'\n'+b, b'42 malformed'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    identity._mount_record(raw, b'42')

    def test_proc_read_failure_returns_no_identity(self):
        with mock.patch.object(identity, '_bounded_read',
                               side_effect=OSError(errno.EACCES, 'private')):
            self.assertIsNone(identity.identify(self.fd))

    def test_pipe_descriptor_never_attempts_ioctl(self):
        read, write = os.pipe()
        try:
            with mock.patch.object(identity.fcntl, 'ioctl') as ioctl:
                self.assertIsNone(identity.identify(read))
                ioctl.assert_not_called()
        finally:
            os.close(read)
            os.close(write)


if __name__ == '__main__':
    unittest.main()
