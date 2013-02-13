#!/usr/bin/env python

"""
Basic command-line usage:
    ./winregfs.py <hivefile> <mountpoint>
    unmount with fusermount -u <mountpoint>
    ./winregfs.py --help for more detailed information.

Quick overview of classes:
    WinRegFS      Mounts the filesystem and accesses the registry
    RegistryTree  All registry access functionality
    MountOptions  Parses special command-line options

See WinRegFS for the top-level filesystem methods.

"""

import os
import sys
import errno
import subprocess
import time
import stat
import argparse

# The registry and FUSE modules.
# Prepending these to the module search path is ugly, but I'm not sure how
# else to make it "just work" for a user running the script (especially with
# the name conflict over the fuse module with "fuse-python"!)
# 
# TODO I think I over-engineered this...
def _fullpath(path):
    try:
        loc = os.readlink(__file__)
    except OSError:
        loc = __file__
    return os.path.join(os.path.dirname(loc), str(path))
sys.path.insert(0, _fullpath('python-registry'))
sys.path.insert(0, _fullpath('fusepy'))
try:
    from Registry import Registry # python-registry -- Will Ballenthin
    from Registry import RegistryParse
except ImportError as ex:
    if __name__ == '__main__':
        print('Error: python-registry not found.  Get it here:')
        print('http://github.com/williballenthin/python-registry/')
        print('and put it next to winregfs.py in a python-registry/ directory.')
        sys.exit(1)
    else:
        raise(ex)
try:
    import fuse # fusepy -- the module by Terence Honles, not fuse-python
    if hasattr(fuse, 'FUSE_PYTHON_API_VERSION'):
        # oops, we got fuse-python.  Wrong module.
        raise ImportError("fusepy expected, but imported fuse-python instead.")
except ImportError as ex:
    if __name__ == '__main__':
        print('Error: fusepy not found.  Get it here:')
        print('http://github.com/terencehonles/fusepy')
        print('and put it next to winregfs.py in a fusepy/ directory.')
        sys.exit(1)
    else:
        raise(ex)


class RegistryTree():
    """Manages reading data from a single registry file.
    
    One of these is used by WinRegFS for all registry access.
    Paths given to methods here are always filesystem paths, but the objects
    returned are of type RegistryKey or RegistryValue.
    
    """
    # These data types will be considered text, as far as conversion to bytes
    # goes.  For example, 84 will become "84", not "T" (84 as ASCII).
    TEXT_TYPES= [Registry.RegSZ, Registry.RegExpandSZ, Registry.RegMultiSZ,
            Registry.RegDWord, Registry.RegQWord]

    def __init__(self):
        self.append_extensions = True  # Append data type to each filename?
        self.append_newline = True  # Add a newline to each "file" (if text)?
        self.__loaded = False

    def load(self, registry):
        """Load the given registry (either a single file or directory).
        
        If a directory is given, it's assumed to be a %WINDIR%\system32\config
        directory with the contents of HKLM inside."""
        # Registry Key       Filesystem Location (Win7)
        # ----------------------------------------------------------------------
        # HKCR               (Composite of \Software\Classes from HKCU and HKLM)
        # HKCU               (Link to current user's key under HKU)
        # HKLM\SAM           %WINDIR%\system32\config\SAM
        # HKLM\SECURITY      %WINDIR%\system32\config\SECURITY
        # HKLM\SOFTWARE      %WINDIR%\system32\config\software
        # HKLM\SYSTEM        %WINDIR%\system32\config\system
        # HKU\.DEFAULT       %WINDIR%\system32\config\default
        # HKU\<SID>          %USERPROFILE%\NTUSER.DAT
        # HKU\<SID>_Classes  %USERPROFILE%\AppData\Local\Microsoft\Windows\UsrClass.dat
        # HKCC               (Generated dynamically at runtime)
        self.registry = registry
        self.hives= {}
        self.hives["HKCR"] = {}
        self.hives["HKCU"] = {}
        self.hives["HKLM"] = {}
        self.hives["HKU"]  = {}
        self.hives["HKCC"] = {}
        if os.path.isdir(registry):
            # With a directory, assume multiple-file usage and try loading
            # HKLM\system.  If that works, also load whichever of the other HKLM
            # files are present.
            self.multifile = True
            hklm = self.hives["HKLM"]
            hku = self.hives["HKU"]
            try:
                self._load_regfile(hklm, "system", "SYSTEM", True)
            # TODO only catch the correct exception
            except Exception:
                raise ValueError("directory specified for registry, but system file couldn't be loaded.")
            self._load_regfile(hklm, "SAM")
            self._load_regfile(hklm, "SECURITY")
            self._load_regfile(hklm, "software", "SOFTWARE")
            self._load_regfile(hku, "default", ".DEFAULT")
        else:
            # With just a file given, ignore all the hives stuff and just
            # give an interface to the specified file.
            self.multifile = False
            self.reg = Registry.Registry(registry)
        self.__loaded = True

    def _load_regfile(self, hkey, regname, keyname=None, strictload=False):
        """Load a single registry file into the tree."""
        path = os.path.join(self.registry, regname)
        keyname = keyname or regname
        try:
            hkey[keyname] = Registry.Registry(path)
        except Exception as ex:
            if strictload:
                raise ex
            hkey[keyname] = None
    
    def key(self, path_to_key):
        """Return the given key object."""
        # Raises Registry.RegistryKeyNotFoundException if it isn't there
        if not self.__loaded:
            raise ValueError("load() must be called first.")
        reg, path_to_key = self._parse_reg(path_to_key)
        try:
            key = reg.open(self._path_to_regpath(path_to_key))
        except RegistryParse.RegistryStructureDoesNotExist:
            raise ValueError("specified key does not exist.")
        return key

    def value(self, path_to_value):
        """Return the given value object.
        
        Keys aren't considered valid for this method, even though they can have
        a value read out of them as far as the registry itself is concerned.
        
        """
        if not self.__loaded:
            raise ValueError("load() must be called first")
        reg, path_to_value = self._parse_reg(path_to_value)
        try:
            reg.open(self._path_to_regpath(path_to_value))      # if this works...
            raise ValueError("specified value does not exist")  # then wait a minute, it's a key
        except RegistryParse.RegistryStructureDoesNotExist:
            pass # OK, it's not a key, at least
        key = self._path_to_regpath(os.path.dirname(path_to_value))       # get corresponding key from path
        val = self._filename_to_regvalue(os.path.basename(path_to_value)) # trim off value name from path
        try:
            keyobj = reg.open(key)    # open the containing key
            value = keyobj.value(val) # ... and extract the right value
        except RegistryParse.RegistryStructureDoesNotExist:
            raise ValueError("specified value does not exist")
        return value

    def _parse_reg(self, path):
        """Return the registry object and subpath for the given global path."""
        if self.multifile:
            parts = path.strip('/').split('/', 2)
            if len(parts) < 3:
                raise ValueError("Can only extract objects under a specific hive.")
            hkey, regkey, path = parts
            try:
                reg = self.hives[hkey][regkey]
            except KeyError:
                raise ValueError("specified item does not exist.")
        else:
            reg = self.reg
        return reg, path

    def bytestr(self, path_to_value):
        """Return a byte string representation of the given value."""

        # See the documentation for VKRecord.data() in python-registry for
        # a list of data types and how they're handled by that library.
        # 
        # In each case the data is converted into a string of bytes, usually
        # as text (except for binary and unrecognized types).
        # 
        # TODO: double-check each of the data types:
        #    - what should we do with "None" or any unknown type?
        #    - how to handle types unsupported by python-registry?
        #    - what about unicode data?
        # 
        #   Type:        What gets returned:
        #   RegSZ        string, text
        #   RegExpandSZ  string, text 
        #   RegMultiSZ   string, multi-line text
        #   RegDWord     string, integer
        #   RegQWord     string, integer
        #   RegBin       binary data
        #   None         ? 
        #   (Others)     ?
        value = self.value(path_to_value)

        nl = "\n"
        data = value.value()
        t = value.value_type()

        # String types -
        # Should just stay as strings.
        if t == Registry.RegSZ or t == Registry.RegExpandSZ:
            data = str(data)
        # Multiple strings - 
        # Join them together with newlines into a single string.
        elif t == Registry.RegMultiSZ:
            data = str(nl.join(data))
        # 32-bit or 64-bit integers -
        # Cast them as a string.
        elif t == Registry.RegDWord or t == Registry.RegQWord:
            data = str(data)
        # Binary - 
        # Just leave alone.
        elif t == Registry.RegBin:
                data = data
        # "None" (??) -
        # Not sure what to do with this.
        elif t == Registry.RegNone: 
            data = data # ??
        # And for any unexpected types, just leave the data alone.

        # A newline on the end of each "file" looks nicer in most cases.
        # Avoid adding an extra newline if there already is one, though, and
        # only add it from types that are considered text as they're parsed
        # in this method, and non-empty values.
        if self.append_newline and t in self.__class__.TEXT_TYPES and (data and data[-1] != nl):
            data = data + nl
        return data

    def items(self, path_to_key):
        """Return a list of all keys and values under the given key path.
        
        This also handles adding file extensions, if append_exensions is set.
        
        """
        if not self.__loaded:
            raise ValueError("load() must be called first.")
        # For multifile:
        #   Case 1: /hivekey/registry/path
        #   Case 2: /hivekey/registry
        #   Case 3: /hivekey
        #   Case 4: /
        if self.multifile:
            parts = path_to_key.strip('/').split('/', 2)
            if len(parts) >= 3:
                hkey, regkey, subpath = parts
                try:
                    reg = self.hives[hkey][regkey]
                except KeyError:
                    raise ValueError("specified key does not exist.")
                return self._items_for_reg(reg, subpath)
            if len(parts) == 2:
                hkey, regkey = parts
                subpath = '/'
                try:
                    reg = self.hives[hkey][regkey]
                except KeyError:
                    raise ValueError("specified key does not exist.")
                return self._items_for_reg(reg, subpath) 
            if len(parts) == 1 and parts[0]:
                try:
                    return self.hives[parts[0]].keys()
                except KeyError:
                    raise ValueError("specified key does not exist.")
            return self.hives.keys()
        return self._items_for_reg(self.reg, path_to_key)

    def _items_for_reg(self, reg, path_to_key):
        try:
            key = reg.open(self._path_to_regpath(path_to_key))
        except RegistryParse.RegistryStructureDoesNotExist:
            raise ValueError("specified key does not exist.")
        names = []
        # Convert these into names.  how do I do "map" in python, again?
        for k in key.subkeys():
            names.append(k.name())
        # Include values in this list also.
        # Add an extension for the "fileytpe" if that option is set.
        for v in key.values():
            name = v.name()
            if self.append_extensions:
                name = name + "." + v.value_type_str()
            names.append(name)
        return names

    def stat(self, path):
        st = self._reg_object_stat()
        # Key (emulated directory)
        # If this works, we can just stick with the defaults for a directory
        try:
            items = self.items(path)
        # Otherwise, Value (emulate file)
        except ValueError:
            data = self.bytestr(path)
            st["st_mode"] = stat.S_IFREG | 0o644 # regular file, rw-r--r--
            st["st_nlink"] = 1 # just one hard link for our regular files
            st["st_size"] = len(data)
        # Oh, and if it was a real key, we can get the modification time.
        # (The runaround with the time functions is required to convert
        # the datetime object into the integer FUSE expects.)  If it wasn't a
        # real key (e.g., hivekey) just stick with the default.
        else:
            try:
                key = self.key(path)
            except ValueError:
                pass
            else:
                st["st_mtime"] = time.mktime(key.timestamp().timetuple())
        return st

    # Some utilities

    def _path_to_regpath(self, path):
        """Convert a filesystem path into a vaild registry path."""
        # All thsi actually does is swap the slashes.
        return path.lstrip('/').replace("/","\\")

    def _filename_to_regvalue(self, name):
        """Convert a filename into a valid registry value name."""
        # All this actually does is trim off the extension, if there is one.
        if self.append_extensions:
            name = name.rsplit('.', 1)[0] 
        return name

    def _reg_object_stat(self):
        """Set up a dictionary of file stat values with reasonable defaults."""
        # These assume a directory (registry key) by default.
        # All time values except modification time for keys are zero right now
        # since I don't have a good way to get at that data (and don't want to
        # get involved in tracking access times here!)
        s = dict()
        s["st_mode"]  = stat.S_IFDIR | 0o755 # defaulting to drwxr-xr-x
        s["st_ino"]   = 0 # inode number.  I think we can leave this at 0.
        s["st_dev"]   = 0 # device ID.  Dito for this one.
        s["st_nlink"] = 2 # 2 hard links -- a good default for directories.
        s["st_uid"]   = 0 # user is root by default
        s["st_gid"]   = 0 # group is root by default
        s["st_size"]  = 0 # file size (bytes)
        s["st_atime"] = 0 # file access time (seconds from epoch)
        s["st_mtime"] = 0 # file modification time (seconds from epoch)
        s["st_ctime"] = 0 # stat change time (seconds from epoch)
        return s


class WinRegFS(fuse.Operations):
    """Collection of filesystem operations for interfacing with the registry.
    
    1. Create a WinRegFS() object
    2. Call setup() to supply the hivefile, mountpoint, and optional settings
    3. Call mount() to actually mount the filesystem

    """
    def __init__(self):
        self.foreground = False # Stay in foreground when mounting FS?
        self.debug = False # Show debug output (implies foreground)?

    def _check_if_mounted(self):
        """True if the filesystem is curently mounted, False otherwise."""
        # I'm doing it this way instead of just storing a "I'm mounted!"
        # attribute, since that could become stale-- for example,
        # `fusermount -u mountpoint` could be called somewhere else on the
        # system after mount() is called here, without calling unmount().

        # Loop over the lines of /proc/mounts, looking for a case where both the
        # first and second items match the FS name and the current mountpoint,
        # respectively.  (Spaces in mountpoints are escaped with \040, so we
        # have to watch out for that.)
        name = self.fuse_options["fsname"]
        mountpoint = self.mountpoint.replace(' ', '\\040')
        with open('/proc/mounts', 'r') as f:
            for line in f:
                source, dest = line.split()[:2]
                if source == name and dest == mountpoint:
                    return True # Both "device" and mountpoint match!
        return False # If there was no match, we're not mounted.

    mounted = property(_check_if_mounted)
    """True if the filesystem is currently mounted, False otherwise."""

    def setup(self, hivefile, mountpoint, append_newline=None,
            append_extensions=None, foreground=None, debug=None, options=None):
        """Parse given mount settings into attributes and open the hivefile."""
        ### Parse and check the hivefile and mountpoint
        hivefile = os.path.abspath(hivefile)
        self.tree = RegistryTree()
        try:
            self.tree.load(hivefile)
            # TODO only catch intended exceptions!
        except Exception:
            raise ValueError('"' + hivefile + '"' +
                    " could not be loaded as a registry hivefile or directory")
        self.mountpoint = os.path.abspath(mountpoint)
        isdir = os.path.isdir(self.mountpoint)
        iswriteable = os.access(self.mountpoint, os.W_OK)
        if not isdir or not iswriteable:
            raise ValueError('"' + mountpoint + '"' +
                    " must be a writeable directory to be used as a mountpoint")

        ### Set up some other assorted settings
        # TODO: for append_extensions, have an option to use this distinction
        # for file extensions, too; use .txt for types in TextTypes and .bin
        # otherwise, for example.  append_newline could also have a choice
        # between never, auto, and always for different situations.
        if append_newline != None:
            self.tree.append_newline = append_newline
        if append_extensions != None:
            self.tree.append_extensions = append_extensions
        if foreground != None:
            self.foreground = foreground
        if debug != None:
            self.debug = debug
            if self.debug:
                self.foreground = True

        ### Handle other FUSE options
        self.fuse_options = options or {}
        # Default to setting the filesystem name to the hivefile,
        # unless one has been specified explicitly.
        if not self.fuse_options.has_key("fsname"):
           self.fuse_options["fsname"] = hivefile
        # "rw" isn't an option right now.
        self.fuse_options["ro"] = True

    def mount(self):
        """Mount the filesystem.  setup() must be called first."""
        # Since an instance of this class *is* a fuse.Operations object,
        # it just passes itself along into FUSE() here.
        # TODO check that setup() completed successfully;
        # possibly accept setup's options here and call if needed?
        #
        # There are two possible cases depended on self.foreground's value:
        # True:  Call fuse.FUSE() without forking, and block until the
        #        filesystem is unmounted elsewhere
        # False: Fork, then call fuse.FUSE() in the child process and just
        #        just return in the parent process without doing anything
        #        else.
        # 
        # I imagine there's probably a much better way to do this, but I'm
        # not sure what it is.
        child_pid = 0
        if not self.foreground:
            child_pid = os.fork()
        if not child_pid: # PID is 0; either child process or we're not forking.
            fuse.FUSE(self, self.mountpoint, foreground=self.foreground,
                    debug=self.debug, **self.fuse_options)

    def unmount(self):
        """Unmount the filesystem."""
        # This is kind of dumb...
        subprocess.call(["fusermount", "-u", self.mountpoint])

    # FS Read methods
    # It looks like in this implementation it's only essential to define
    # getattr(), readdir(), and read()!
    # 
    # Note that there isn't much error checking.  I think this should be OK,
    # because FUSE will enforce most requirements before calling these methods.
    # See this page for details:
    # http://sourceforge.net/apps/mediawiki/fuse/index.php?title=FuseInvariants
    #
    # About FS Write methods:
    # fusepy sets write operations to raise EROFS (error: read-only filesystem)
    # for write operations, so no changes are needed.


    def getattr(self, path, fh=None):
        """Return a dict of file attributes for the given file/directory."""
        # This will work for either file or directory, but raises ValueError if
        # it doesn't exist-- convert that error to ENOENT if it happens.
        try:
            st = self.tree.stat(path)
        except ValueError:
            raise fuse.FuseOSError(errno.ENOENT)
        # Apply UID and GID from fuse's context.  The other values are fine
        # as-is.
        st["st_uid"], st["st_gid"] = fuse.fuse_get_context()[0:2]
        return st

    def readdir(self, path, fh):
        """Return a list of all items in the given path (including . and ..)."""
        dirents = ['.', '..']
        dirents.extend(self.tree.items(path))
        return dirents

    def read(self, path, size, offset, fh):
        """Return data at the given path, with given offset and size in bytes."""
        # "Invariants" aside, fuse will happily pass a directory into read().
        # But, bytestr won't allow it -- just catch that error and convert it
        # to EISDIR if it happens.
        try:
            # I would have thought size and offset were essential for programs
            # like head and tail to work properly, but actually it seems fine
            # even if we just return all of the data and ignore those arguments.
            # I don't know why...
            data = self.tree.bytestr(path)
            return data[offset:offset+size]
        except ValueError:
            raise fuse.FuseOSError(errno.EISDIR)

    # FS Extended Attribute Methods
    # getxattr() and listattr() are all that are needed here.  Leaving out
    # setxattr() works since fusepy's defaults do the trick.  These methods
    # check for support first (or try, anyway) because overriding the defaults
    # *without* support in the OS will cause "bad address" errors.

    # Mapping of names <-> methods to call for reading extended attributes.
    # These little methods each take a RegistryValue and return a string,
    # and XATTRS below maps an xattr name to each method.  (This way the xattr
    # methods don't have to each know about the details.)

    def get_value_str(val):
        """Return the string representation of the type of the given RegistryValue."""
        return val.value_type_str()

    def get_is_text(val):
        """Return "True" if the given RegistryValue would be shown as text, "False" otherwise."""
        return str(val.value_type() in RegistryTree.TEXT_TYPES)

    XATTRS = {}
    XATTRS["user.registry.datatype"] = get_value_str
    XATTRS["user.registry.text"]     = get_is_text

    # TODO: what's position?
    def getxattr(self, path, name, position=0):
        if hasattr(errno, "ENOATTR"):
            """Return the requested attribute for the given path."""
            try:
                items = self.tree.items(path)
            except ValueError:
                val = self.tree.value(path)
                try:
                    return WinRegFS.XATTRS[name](val)
                except KeyError:
                    #return ""
                    pass # raises exception below
            raise fuse.FuseOSError(errno.ENOATTR)
        else:
            return super(self.__class__, self).getxattr(path, name, position)

    def listxattr(self, path):
        """Return a list of extended attributes available for the given path.
        
        Currently there are no xattrs for directories, so an empty list is given
        for those cases.  Files support a datatype attribute and a text (boolean
        flag for non-binary data) attribute.
        
        """
        # Key:   Fall through to returning an empty list
        # Value: Return all supported xattrs
        if hasattr(errno, "ENOATTR"):
            try:
                self.tree.items(path)
            except ValueError:
                return WinRegFS.XATTRS.keys()
            return []
        else:
            return super(self.__class__, self).listxattr(path)


# All the command-line argument parsring code,
# and the obligatory main() function and idiom.
# The only real FS code here is creating a WinRegFS(),
# calling setup(), and calling mount().
#
# (I think this might go in circles a bit, since I then turn around and pass the
# formated options to fusepy, which turns them into an argv list and gives them
# to fuse.  Oh well...)

mo_parser = argparse.ArgumentParser(add_help=False)
mo_group = mo_parser.add_argument_group('Mount Options', 'Options affecting the mounted filesystem')
mo_setup = {"type": str, "choices": ("yes", "no"), "default": "yes", "const": "yes", "nargs": "?"}
mo_group.add_argument('-n', '--append-newline', help="append newlines to file data when appropriate (default: no)", **mo_setup)
mo_group.add_argument('-e', '--append-extensions', help="append extensions to file names to match data types (default: yes).  Also available as an extended file attribute.", **mo_setup)

# A list of fuse options I know of that can only be specified with -o.
# I've never actually found a definitive list anywhere; this just came from the
# output of an example FUSE program with "--help" using the official bindings.
FUSE_OPTIONS = ["allow_other", "allow_root", "nonempty", "default_permissions",
        "fsname", "subtype", "large_read", "max_read", "hard_remove", "use_ino",
        "readdir_ino", "direct_io", "kernel_cache", "auto_cache",
        "noauto_cache", "umask", "uid", "gid", "entry_timeout",
        "negative_timeout", "attr_timeout", "ac_attr_timeout", "intr",
        "intr_signal", "modules", "max_write", "max_readahead", "async_read",
        "sync_read", "atomic_o_trunc", "big_writes", "no_remote_lock", "subdir",
        "rellinks", "norellinks", "from_code", "to_code"]


class MountOptions(argparse.Action):
    """Custom argparse.Action for mountpoint options given as -o opt=value1,opt2,..."""
    
    # This just reformats the arguments and parses them again with the mo_parser
    # settings and puts the results in the same namespace as the original
    # parser.  Options for FUSE itself are put in a dict (namespace.options) and
    # can then just be passed to FUSE directly.  But, that means no error checking
    # is done here for those, except that the options are recognized.
    def __call__(self, parser, namespace, values, option_string=None):
        args = []
        for option in values.split(','):
            key, val = option.partition('=')[::2]
            if key in FUSE_OPTIONS:
                namespace.options = namespace.options or {}
                namespace.options[key] = val or True
            else:
                args.append('--' + str(key))
                if val:
                    args.append(str(val))
        temp_parser = argparse.ArgumentParser(parents=[mo_parser])
        temp_parser.parse_args(args, namespace=namespace)

parser = argparse.ArgumentParser(parents=[mo_parser],
        description='Mount a Windows registry hivefile as a filesystem.')
parser.add_argument('hivefile', help="hivefile to mount")
parser.add_argument('mountpoint', help="path to filesystem mountpoint")
parser.add_argument('-f', '--foreground', action="store_true",
        help="run in foreground (default: False)",)
parser.add_argument('-d', '--debug', action="store_true",
        help="show debugging output on stdout.  Implies -f. (default: False)")
parser.add_argument('-o', '--options', metavar="opt,[opt...]", action=MountOptions, help="alternate syntax for mount options and generic FUSE options.  For example, -o append-newline=no,append-extensions=yes.  Any generic FUSE options given here will be passed directly to FUSE.")

def main(args):
    settings = parser.parse_args(args[1:])
    regfs = WinRegFS()
    try:
        regfs.setup(**vars(settings))
    except ValueError as e:
        print("Error: " + str(e))
        return 1
    else:
        regfs.mount()
    return 0

if __name__ == '__main__':
    status = main(sys.argv)
    sys.exit(status)
