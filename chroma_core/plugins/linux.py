
# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

from chroma_core.lib.storage_plugin.plugin import StoragePlugin
from chroma_core.lib.storage_plugin.resource import StorageResource, ScannableId, GlobalId

from chroma_core.lib.storage_plugin import attributes
from chroma_core.lib.storage_plugin import builtin_resources

# This plugin is special, it uses Hydra's built-in infrastructure
# in a way that third party plugins can't/shouldn't/mustn't
from chroma_core.models import ManagedHost


class DeviceNode(StorageResource):
    # NB ideally we would get this from exploring the graph rather than
    # tagging it onto each one, but this is simpler for now - jcs
    host = attributes.ResourceReference()
    path = attributes.PosixPath()
    class_label = 'Device node'

    def get_label(self):
        path = self.path
        strip_strings = ["/dev/",
                         "/dev/mapper/",
                         "/dev/disk/by-id/",
                         "/dev/disk/by-path/"]
        strip_strings.sort(lambda a, b: cmp(len(b), len(a)))
        for s in strip_strings:
            if path.startswith(s):
                path = path[len(s):]
        return "%s:%s" % (self.host.get_label(), path)


class PluginAgentResources(StorageResource):
    identifier = GlobalId('host_id', 'plugin_name')
    host_id = attributes.Integer()
    plugin_name = attributes.String()


class HydraHostProxy(StorageResource):
    # FIXME using address here is troublesome for hosts whose
    # addresses might change.  However it is useful for doing
    # an update_or_create on VMs discovered on controllers.  Hmm.
    # I wonder if what I really want is a HostResource base and then
    # subclasses for on-controller hosts (identified by controller+index)
    # and separately for general hosts (identified by ManagedHost.pk)
    identifier = GlobalId('host_id')

    host_id = attributes.Integer()
    virtual_machine = attributes.ResourceReference(optional = True)

    def get_label(self, parent = None):
        host = ManagedHost._base_manager.get(pk=self.host_id)
        return "%s" % host


class ScsiDevice(builtin_resources.LogicalDrive):
    identifier = GlobalId('serial')

    serial = attributes.String(subscribe = 'scsi_serial')

    class_label = "SCSI device"

    def get_label(self, ancestors = []):
        if self.serial[0] == 'S':
            return self.serial[1:]
        else:
            return self.serial


class UnsharedDeviceNode(DeviceNode):
    """A device node whose underlying device has no SCSI ID
    and is therefore assumed to be unshared"""
    identifier = ScannableId('path')

    class_label = "Local disk"

    def get_label(self, ancestors = []):
        if self.path.startswith("/dev/"):
            return self.path[5:]
        else:
            return self.path


class UnsharedDevice(builtin_resources.LogicalDrive):
    identifier = ScannableId('path')
    # Annoying duplication of this from the node, but it really
    # is the closest thing we have to a real ID.
    path = attributes.PosixPath()

    def get_label(self):
        return self.path


class ScsiDeviceNode(DeviceNode):
    """SCSI in this context is a catch-all to refer to
    block devices which look like real disks to the host OS"""
    identifier = ScannableId('path')
    #class_label = "SCSI device node"
    host = attributes.ResourceReference()


class MultipathDeviceNode(DeviceNode):
    identifier = ScannableId('path')
    class_label = "Multipath device node"


class LvmDeviceNode(DeviceNode):
    identifier = ScannableId('path')
    class_label = "LVM device node"

    def get_label(self):
        # LVM devices are only presented once per host,
        # so just need to say which host this device node is for
        return "%s" % (self.host.get_label())


# FIXME: partitions should really be GlobalIds (they can be seen from more than
# one host) where the ID is their number plus the a foreign key to the parent
# ScsiDevice or UnsharedDevice(HYD-272)
# TODO: include containng object get_label in partition get_label
class Partition(builtin_resources.LogicalDrive):
    identifier = ScannableId('path')
    class_label = "Linux partition"
    path = attributes.PosixPath()

    def get_label(self):
        return self.path


class PartitionDeviceNode(DeviceNode):
    identifier = ScannableId('path')
    class_label = "Linux partition"


class LocalMount(StorageResource):
    """A local filesystem consuming a storage resource -- reported so that
       hydra knows not to try and use the consumed resource for Lustre e.g.
       minor things like your root partition."""
    identifier = ScannableId('mount_point')

    fstype = attributes.String()
    mount_point = attributes.String()


class Linux(StoragePlugin):
    internal = True

    def __init__(self, *args, **kwargs):
        super(Linux, self).__init__(*args, **kwargs)

        self._scsi_devices = set()

    def teardown(self):
        self.log.debug("Linux.teardown")

    def agent_session_start(self, host_resource, data):
        devices = data

        lv_block_devices = set()
        for vg, lv_list in devices['lvs'].items():
            for lv_name, lv in lv_list.items():
                try:
                    lv_block_devices.add(lv['block_device'])
                except KeyError:
                    # An inactive LV has no block device
                    pass
        mpath_block_devices = set()
        for mp_name, mp in devices['mpath'].items():
            mpath_block_devices.add(mp['block_device'])

        dm_block_devices = lv_block_devices | mpath_block_devices

        # List of BDs with serial numbers that aren't devicemapper BDs
        devs_by_serial = {}
        for bdev in devices['devs'].values():
            serial = bdev['serial']
            if not bdev['major_minor'] in dm_block_devices:
                if serial != None and not serial in devs_by_serial:
                    # NB it's okay to have multiple block devices with the same
                    # serial (multipath): we just store the serial+size once
                    devs_by_serial[serial] = {
                            'serial': serial,
                            'size': bdev['size']
                            }

        # Resources for devices with serial numbers
        res_by_serial = {}
        for dev in devs_by_serial.values():
            res, created = self.update_or_create(ScsiDevice, serial = dev['serial'], size = dev['size'])
            self._scsi_devices.add(res)
            res_by_serial[dev['serial']] = res

        bdev_to_resource = {}
        for bdev in devices['devs'].values():
            # Partitions: we will do these in a second pass once their
            # parents are in bdev_to_resource
            if bdev['parent'] != None:
                continue

            # DM devices: we will do these later
            if bdev['major_minor'] in dm_block_devices:
                continue

            if bdev['serial'] != None:
                lun_resource = res_by_serial[bdev['serial']]
                res, created = self.update_or_create(ScsiDeviceNode,
                                    parents = [lun_resource],
                                    host = host_resource,
                                    path = bdev['path'])
            else:
                res, created = self.update_or_create(UnsharedDevice,
                        path = bdev['path'],
                        size = bdev['size'])
                res, created = self.update_or_create(UnsharedDeviceNode,
                        parents = [res],
                        host = host_resource,
                        path = bdev['path'])
            bdev_to_resource[bdev['major_minor']] = res

        # Okay, now we've got ScsiDeviceNodes, time to build the devicemapper ones
        # on top of them.  These can come in any order and be nested to any depth.
        # So we have to build a graph and then traverse it to populate our resources.
        for bdev in devices['devs'].values():
            if bdev['major_minor'] in lv_block_devices:
                res, created = self.update_or_create(LvmDeviceNode,
                                    host = host_resource,
                                    path = bdev['path'])
            elif bdev['major_minor'] in mpath_block_devices:
                res, created = self.update_or_create(MultipathDeviceNode,
                                    host = host_resource,
                                    path = bdev['path'])
            elif bdev['parent']:
                res, created = self.update_or_create(PartitionDeviceNode,
                        host = host_resource,
                        path = bdev['path'])
            else:
                continue

            bdev_to_resource[bdev['major_minor']] = res

        for bdev in devices['devs'].values():
            if bdev['parent'] == None:
                continue

            this_node = bdev_to_resource[bdev['major_minor']]
            parent_resource = bdev_to_resource[bdev['parent']]

            partition, created = self.update_or_create(Partition,
                    parents = [parent_resource],
                    size = bdev['size'],
                    path = bdev['path'])

            this_node.add_parent(partition)

        # Now all the LUNs and device nodes are in, create the links between
        # the DM block devices and their parent entities.
        vg_uuid_to_resource = {}
        for vg in devices['vgs'].values():
            # Create VG resource
            vg_resource, created = self.update_or_create(LvmGroup,
                    uuid = vg['uuid'],
                    name = vg['name'],
                    size = vg['size'])
            vg_uuid_to_resource[vg['uuid']] = vg_resource

            # Add PV block devices as parents of VG
            for pv_bdev in vg['pvs_major_minor']:
                if pv_bdev in bdev_to_resource:
                    vg_resource.add_parent(bdev_to_resource[pv_bdev])

        for vg, lv_list in devices['lvs'].items():
            for lv_name, lv in lv_list.items():
                vg_info = devices['vgs'][vg]
                vg_resource = vg_uuid_to_resource[vg_info['uuid']]

                # Make the LV a parent of its device node on this host
                lv_resource, created = self.update_or_create(LvmVolume,
                        parents = [vg_resource],
                        uuid = lv['uuid'],
                        name = lv['name'],
                        vg = vg_resource,
                        size = lv['size'])

                try:
                    lv_bdev = bdev_to_resource[lv['block_device']]
                    lv_bdev.add_parent(lv_resource)
                except KeyError:
                    # Inactive LVs have no block device
                    pass

        for mpath_alias, mpath in devices['mpath'].items():
            mpath_bdev = bdev_to_resource[mpath['block_device']]
            mpath_parents = [bdev_to_resource[n['major_minor']] for n in mpath['nodes']]
            for p in mpath_parents:
                mpath_bdev.add_parent(p)

        for bdev, (mntpnt, fstype) in devices['local_fs'].items():
            bdev_resource = bdev_to_resource[bdev]
            self.update_or_create(LocalMount,
                    parents=[bdev_resource],
                    mount_point = mntpnt,
                    fstype = fstype)

    def update_scan(self, scannable_resource):
        pass


class LvmGroup(builtin_resources.StoragePool):
    identifier = GlobalId('uuid')

    uuid = attributes.Uuid()
    name = attributes.String()
    size = attributes.Bytes()

    icon = 'lvm_vg'
    class_label = 'Volume group'

    def get_label(self, parent = None):
        return self.name


class LvmVolume(builtin_resources.LogicalDrive):
    # Q: Why is this identified by LV UUID and VG UUID rather than just
    #    LV UUID?  Isn't the LV UUID unique enough?
    # A: We're matching LVM2's behaviour.  If you e.g. image a machine that
    #    has some VGs and LVs, then if you want to disambiguate them you run
    #    'vgchange -u' to get a new VG UUID.  However, there is no equivalent
    #    command to reset LV uuid, because LVM finds two LVs with the same UUID
    #    in VGs with different UUIDs to be unique enough.
    identifier = GlobalId('uuid', 'vg')

    vg = attributes.ResourceReference()
    uuid = attributes.Uuid()
    name = attributes.String()

    icon = 'lvm_lv'
    class_label = 'Logical volume'

    def get_label(self, ancestors = []):
        return "%s-%s" % (self.vg.name, self.name)
