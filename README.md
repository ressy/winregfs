winregfs
========

Mount a Windows registry file as a read-only filesystem.

For the moment I should mention that I've *barely* tested this at all.  I don't
think it could do anything awful, since python-registry is read-only, but it
could at least do something extremely illogical :)

Setup
-----

This requires a working [FUSE](http://fuse.sourceforge.net/) installation,
[Python](http://www.python.org/) 2.7, and these two other projects:
 * [fusepy](https://github.com/terencehonles/fusepy)
 * [python-registry](https://github.com/williballenthin/python-registry)

If they're not installed globally, it assumes they're stored in their own
directories, under those names, alongside winregfs.py. 

Usage
-----

Just run ./winregfs.py --help for some details, but the required arguments are
very simple.  For example:

    $ ./winregfs.py NTUSER.DAT mountpoint/

    $ ls -l mountpoint
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 AppEvents
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 Console
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 Control Panel
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 EUDC
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 Environment
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 Identities
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 Keyboard Layout
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 Network
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 Printers
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 Software
    drwxr-xr-x 2 jesse jesse 0 May 19  2011 System

I've tried to keep it tidy so it plays nice when imported as a Python module,
too:

    >>> from winregfs import WinRegFS
    >>> fs = WinRegFS()
    >>> fs.setup('NTUSER.DAT', 'mountpoint/')
    >>> fs.mount()
    >>> fs.mounted
    True
    >>> fs.unmount()
    >>> fs.mounted
    False

Finally, a link from wherever winregfs.py is to /sbin/mount.winregfs will allow
this usage:

    mount -t winregfs NTUSER.DAT mountpoint/

and also the corresponding usage in /etc/fstab, as with a "real" filesystem.

Limitations
-----------

To name a few:
 * read-only access
 * only modification times for directories (keys) are currently given
 * Types for values are given as file extensions right now (kinda ugly)
 * Certain registry data types aren't supported (more on this later)
 * Did I mention I've barely tested this?

Credits
-------

This is basically just a little bit of glue between python-registry and fusepy
to hand data from the former to the latter-- they've already done the hard work.
Thanks to both!
