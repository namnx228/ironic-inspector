# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Standard set of plugins."""

import logging
import sys

from ironic_discoverd.common.i18n import _, _LC, _LI, _LW
from ironic_discoverd import conf
from ironic_discoverd.plugins import base
from ironic_discoverd import utils


LOG = logging.getLogger('ironic_discoverd.plugins.standard')


class SchedulerHook(base.ProcessingHook):
    """Nova scheduler required properties."""

    KEYS = ('cpus', 'cpu_arch', 'memory_mb', 'local_gb')

    def before_processing(self, node_info):
        """Validate that required properties are provided by the ramdisk."""
        missing = [key for key in self.KEYS if not node_info.get(key)]
        if missing:
            raise utils.Error(
                _('The following required parameters are missing: %s') %
                missing)

        LOG.info(_LI('Discovered data: CPUs: %(cpus)s %(cpu_arch)s, '
                     'memory %(memory_mb)s MiB, disk %(local_gb)s GiB'),
                 {key: node_info.get(key) for key in self.KEYS})

    def before_update(self, node, ports, node_info):
        """Update node with scheduler properties."""
        overwrite = conf.getboolean('discoverd', 'overwrite_existing')
        patch = [{'op': 'add', 'path': '/properties/%s' % key,
                  'value': str(node_info[key])}
                 for key in self.KEYS
                 if overwrite or not node.properties.get(key)]
        return patch, {}


VALID_ADD_PORTS_VALUES = ('all', 'active', 'pxe')


class ValidateInterfacesHook(base.ProcessingHook):
    """Hook to validate network interfaces."""

    def __init__(self):
        if conf.get('discoverd', 'add_ports') not in VALID_ADD_PORTS_VALUES:
            LOG.critical(_LC('Accepted values for [discoverd]add_ports are '
                             '%(valid)s, got %(actual)s'),
                         {'valid': VALID_ADD_PORTS_VALUES,
                          'actual': conf.get('discoverd', 'add_ports')})
            sys.exit(1)

    def _ports_to_add(self):
        if conf.getboolean('discoverd', 'ports_for_inactive_interfaces'):
            LOG.warning(_LW('Using deprecated option '
                            '[discoverd]ports_for_inactive_interfaces'))
            return 'all'
        else:
            return conf.get('discoverd', 'add_ports')

    def before_processing(self, node_info):
        """Validate information about network interfaces."""
        bmc_address = node_info.get('ipmi_address')
        if not node_info.get('interfaces'):
            raise utils.Error(_('No interfaces supplied by the ramdisk'))

        valid_interfaces = {
            n: iface for n, iface in node_info['interfaces'].items()
            if utils.is_valid_mac(iface.get('mac'))
        }

        ports_to_add = self._ports_to_add()
        pxe_mac = node_info.get('boot_interface')

        if ports_to_add == 'pxe' and pxe_mac:
            LOG.info(_LI('PXE boot interface was %s'), pxe_mac)
            if '-' in pxe_mac:
                # pxelinux format: 01-aa-bb-cc-dd-ee-ff
                pxe_mac = pxe_mac.split('-', 1)[1]
                pxe_mac = pxe_mac.replace('-', ':').lower()

            valid_interfaces = {
                n: iface for n, iface in valid_interfaces.items()
                if iface['mac'].lower() == pxe_mac
            }
        elif ports_to_add != 'all':
            valid_interfaces = {
                n: iface for n, iface in valid_interfaces.items()
                if iface.get('ip')
            }

        if not valid_interfaces:
            raise utils.Error(_('No valid interfaces found for node with '
                                'BMC %(ipmi_address)s, got %(interfaces)s') %
                              {'ipmi_address': bmc_address,
                               'interfaces': node_info['interfaces']})
        elif valid_interfaces != node_info['interfaces']:
            LOG.warning(_LW(
                'The following interfaces were invalid or not eligible in '
                'introspection data for node with BMC %(ipmi_address)s and '
                'were excluded: %(invalid)s'),
                {'invalid': {n: iface
                             for n, iface in node_info['interfaces'].items()
                             if n not in valid_interfaces},
                 'ipmi_address': bmc_address})
            LOG.info(_LI('Eligible interfaces are %s'), valid_interfaces)

        node_info['all_interfaces'] = node_info['interfaces']
        node_info['interfaces'] = valid_interfaces
        valid_macs = [iface['mac'] for iface in valid_interfaces.values()]
        node_info['macs'] = valid_macs


class RamdiskErrorHook(base.ProcessingHook):
    """Hook to process error send from the ramdisk."""

    def before_processing(self, node_info):
        if not node_info.get('error'):
            return

        raise utils.Error(_('Ramdisk reported error: %s') % node_info['error'])
