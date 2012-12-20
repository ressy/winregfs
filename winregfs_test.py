#!/usr/bin/env python
from winregfs import RegistryTree
import unittest

class TestRegistryTree_Basic(unittest.TestCase):
    """Most basic RegistryTree test case."""

    def setUp(self):
        self.tree = RegistryTree()
        self.hivefile       = "../NTUSER.DAT"
        self.hivefile_bad   = "/does/not/exist.dat"
        self.key_path       = "/AppEvents/Schemes/Apps/Explorer/"
        self.key_name       = "Explorer"
        self.key_path_bad   = "/does/not/exist"
        self.value_path     = "/AppEvents/Schemes/Apps/Explorer/(default).RegSZ"
        self.value_value    = u"Windows Explorer"
        self.value_bytes    = "Windows Explorer\n"
        self.value_path_bad = "/does/not/exist.RegSZ"

    def test_load(self):
        with self.assertRaises(IOError):
            self.tree.load(self.hivefile_bad)
        self.tree.load(self.hivefile)

    def test_key(self):
        # Haven't called load() yet
        with self.assertRaises(ValueError):
            self.tree.key(self.key_path)
        self.tree.load(self.hivefile)
        # Path doesn't exist
        with self.assertRaises(ValueError):
            self.tree.key(self.key_path_bad)
        # Can't get key on a value
        for path in (self.value_path, self.value_path_bad):
            with self.assertRaises(ValueError):
                self.tree.key(path)
        # Test an actual key that should work
        key = self.tree.key(self.key_path)
        self.assertEqual(key.name(), self.key_name)

    def test_value(self):
        # Haven't called load() yet
        with self.assertRaises(ValueError):
            self.tree.value(self.value_path)
        self.tree.load(self.hivefile)
        # Path doesn't exist
        with self.assertRaises(ValueError):
            self.tree.value(self.value_path_bad)
        # Can't get value on a key
        for path in (self.key_path, self.key_path_bad):
            with self.assertRaises(ValueError):
                self.tree.value(path) 
        # Test an actual value that should work
        value = self.tree.value(self.value_path)
        self.assertEqual(value.value(), self.value_value)

    def test_items(self):
        # Haven't called load() yet
        with self.assertRaises(ValueError):
            self.tree.items(self.key_path)
        self.tree.load(self.hivefile)
        # Path doesn't exist
        with self.assertRaises(ValueError):
            self.tree.items(self.key_path_bad)
        # Can't list items under a value
        for path in (self.value_path, self.value_path_bad):
            with self.assertRaises(ValueError):
                self.tree.items(path)
        items = self.tree.items(self.key_path)
        # TODO: check list of items
    
    def test_bytestr(self):
        self.tree.load(self.hivefile)
        data = self.tree.bytestr(self.value_path)
        self.assertEqual(data, self.value_bytes)
        # TODO also try other data types

    def test_stat(self):
        # Haven't called load() yet
        with self.assertRaises(ValueError):
            self.tree.stat(self.key_path)
        self.tree.load(self.hivefile)
        # Path doesn't exist
        with self.assertRaises(ValueError):
            self.tree.stat(self.key_path_bad)
        with self.assertRaises(ValueError):
            self.tree.stat(self.value_path_bad)

        # Test an actual key that should work
        st_key = self.tree.stat(self.key_path)
        self.assertEqual(st_key["st_mode"],  0o40755) # drwxr-xr-x 
        self.assertEqual(st_key["st_ino"],   0)
        self.assertEqual(st_key["st_dev"],   0)
        self.assertEqual(st_key["st_nlink"], 2)
        self.assertEqual(st_key["st_uid"],   0)
        self.assertEqual(st_key["st_gid"],   0)
        self.assertEqual(st_key["st_size"],  0)
        self.assertEqual(st_key["st_atime"], 0)
        self.assertEqual(st_key["st_mtime"], 1305848118) # Unix epoch time
        self.assertEqual(st_key["st_ctime"], 0)
        with self.assertRaises(KeyError):
            st_key["does_not_exist"]

        # Test an actual value that should work
        st_value = self.tree.stat(self.value_path)
        self.assertEqual(st_value["st_mode"],  0o100644) # -rw-r--r-- 
        self.assertEqual(st_value["st_ino"],   0)
        self.assertEqual(st_value["st_dev"],   0)
        self.assertEqual(st_value["st_nlink"], 1)
        self.assertEqual(st_value["st_uid"],   0)
        self.assertEqual(st_value["st_gid"],   0)
        self.assertEqual(st_value["st_size"],  len(self.value_bytes))
        self.assertEqual(st_value["st_atime"], 0)
        self.assertEqual(st_value["st_mtime"], 0)
        self.assertEqual(st_value["st_ctime"], 0)
        with self.assertRaises(KeyError):
            st_value["does_not_exist"]


class TestRegistryTree_NoAppendExtensions(TestRegistryTree_Basic):
    """Test everything as above, but with append_extensions set to False."""

    def setUp(self):
        super(self.__class__, self).setUp()
        self.value_path     = "/AppEvents/Schemes/Apps/Explorer/(default)"
        self.value_path_bad = "/does/not/exist"
        self.tree.append_extensions = False


# TODO try also with other data types
class TestRegistryTree_NoAppendNewline(TestRegistryTree_Basic):
    """Test everything as above, but try with append_newline set to False."""

    def setUp(self):
        super(self.__class__, self).setUp()
        self.value_bytes = self.value_bytes.rstrip("\n")
        self.tree.append_newline = False


class TestRegistryTree_NoAppendAnything(TestRegistryTree_Basic):
    """Combination of both NoAppendNewline and NoAppendExtensions tests."""

    def setUp(self):
        super(self.__class__, self).setUp()
        self.value_bytes = self.value_bytes.rstrip("\n")
        self.value_path     = "/AppEvents/Schemes/Apps/Explorer/(default)"
        self.value_path_bad = "/does/not/exist"
        self.tree.append_extensions = False
        self.tree.append_newline    = False


class TestRegistryTree_Combined(TestRegistryTree_Basic):
    """Test with loading multiple hivefiles into one registry mountpoint."""

    # HKLM or HKEY_LOCAL_MACHINE or ...?
    # SYSTEM or System or system?
    # Even Windows itself isn't consistent.  Be case insensitive for these?
    def setUp(self):
        super(self.__class__, self).setUp()
        self.hivefile       = "../registries/config-example/"
        self.hivefile_bad   = "/does/not/exist.dat"
        self.key_path       = "HKLM/system/Select/"
        self.key_name       = "Select"
        self.key_path_bad   = "/does/not/exist"
        self.value_path     = "HKLM/system/Select/Current.RegDWord"
        self.value_value    = 3
        self.value_bytes    = "3\n"
        self.value_path_bad = "/does/not/exist.RegSZ"

class TestRegistryTree_CombinedAlternate(TestRegistryTree_Basic):
    """Test with loading multiple hivefiles into one registry mountpoint."""

    def setUp(self):
        super(self.__class__, self).setUp()
        self.hivefile       = "../registries/config-example/"
        self.hivefile_bad   = "/does/not/exist.dat"
        self.key_path       = "/"
        self.key_name       = "/"
        self.key_path_bad   = "/does/not/exist"
        self.value_path     = "/HKLM/system/Select/Current.RegDWord"
        self.value_value    = 3
        self.value_bytes    = "3\n"
        self.value_path_bad = "/HKLM"

    def test_key(self):
        # Haven't called load() yet
        with self.assertRaises(ValueError):
            self.tree.key(self.key_path)
        self.tree.load(self.hivefile)
        # Path doesn't exist
        with self.assertRaises(ValueError):
            self.tree.key(self.key_path_bad)
        # Can't get key on a value
        for path in (self.value_path, self.value_path_bad):
            with self.assertRaises(ValueError):
                self.tree.key(path)
        # Can't get a key object for / or /{hivekey}
        with self.assertRaises(ValueError):
            self.tree.key(self.key_path)
        with self.assertRaises(ValueError):
            self.tree.key("/HKLM")


if __name__ == '__main__':
    unittest.main()
    #suite = unittest.TestSuite()
    #suite.addTest(TestRegistryTree_CombinedAlternate('test_items'))
    #unittest.TextTestRunner().run(suite)
