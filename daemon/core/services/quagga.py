"""
quagga.py: defines routing services provided by Quagga.
"""

from core import constants
from core.emulator.enumerations import LinkTypes, NodeTypes
from core.nodes import ipaddress, nodeutils
from core.services.coreservices import CoreService


class Zebra(CoreService):
    name = "zebra"
    group = "Quagga"
    dirs = ("/usr/local/etc/quagga", "/var/run/quagga")
    configs = (
        "/usr/local/etc/quagga/Quagga.conf",
        "quaggaboot.sh",
        "/usr/local/etc/quagga/vtysh.conf",
    )
    startup = ("sh quaggaboot.sh zebra",)
    shutdown = ("killall zebra",)
    validate = ("pidof zebra",)

    @classmethod
    def generate_config(cls, node, filename):
        """
        Return the Quagga.conf or quaggaboot.sh file contents.
        """
        if filename == cls.configs[0]:
            return cls.generateQuaggaConf(node)
        elif filename == cls.configs[1]:
            return cls.generateQuaggaBoot(node)
        elif filename == cls.configs[2]:
            return cls.generateVtyshConf(node)
        else:
            raise ValueError(
                "file name (%s) is not a known configuration: %s", filename, cls.configs
            )

    @classmethod
    def generateVtyshConf(cls, node):
        """
        Returns configuration file text.
        """
        return "service integrated-vtysh-config\n"

    @classmethod
    def generateQuaggaConf(cls, node):
        """
        Returns configuration file text. Other services that depend on zebra
        will have generatequaggaifcconfig() and generatequaggaconfig()
        hooks that are invoked here.
        """
        # we could verify here that filename == Quagga.conf
        cfg = ""
        for ifc in node.netifs():
            cfg += "interface %s\n" % ifc.name
            # include control interfaces in addressing but not routing daemons
            if hasattr(ifc, "control") and ifc.control is True:
                cfg += "  "
                cfg += "\n  ".join(map(cls.addrstr, ifc.addrlist))
                cfg += "\n"
                continue
            cfgv4 = ""
            cfgv6 = ""
            want_ipv4 = False
            want_ipv6 = False
            for s in node.services:
                if cls.name not in s.dependencies:
                    continue
                ifccfg = s.generatequaggaifcconfig(node, ifc)
                if s.ipv4_routing:
                    want_ipv4 = True
                if s.ipv6_routing:
                    want_ipv6 = True
                    cfgv6 += ifccfg
                else:
                    cfgv4 += ifccfg

            if want_ipv4:
                ipv4list = filter(
                    lambda x: ipaddress.is_ipv4_address(x.split("/")[0]), ifc.addrlist
                )
                cfg += "  "
                cfg += "\n  ".join(map(cls.addrstr, ipv4list))
                cfg += "\n"
                cfg += cfgv4
            if want_ipv6:
                ipv6list = filter(
                    lambda x: ipaddress.is_ipv6_address(x.split("/")[0]), ifc.addrlist
                )
                cfg += "  "
                cfg += "\n  ".join(map(cls.addrstr, ipv6list))
                cfg += "\n"
                cfg += cfgv6
            cfg += "!\n"

        for s in node.services:
            if cls.name not in s.dependencies:
                continue
            cfg += s.generatequaggaconfig(node)
        return cfg

    @staticmethod
    def addrstr(x):
        """
        helper for mapping IP addresses to zebra config statements
        """
        if x.find(".") >= 0:
            return "ip address %s" % x
        elif x.find(":") >= 0:
            return "ipv6 address %s" % x
        else:
            raise ValueError("invalid address: %s", x)

    @classmethod
    def generateQuaggaBoot(cls, node):
        """
        Generate a shell script used to boot the Quagga daemons.
        """
        quagga_bin_search = node.session.options.get_config(
            "quagga_bin_search", default='"/usr/local/bin /usr/bin /usr/lib/quagga"'
        )
        quagga_sbin_search = node.session.options.get_config(
            "quagga_sbin_search", default='"/usr/local/sbin /usr/sbin /usr/lib/quagga"'
        )
        return """\
#!/bin/sh
# auto-generated by zebra service (quagga.py)
QUAGGA_CONF=%s
QUAGGA_SBIN_SEARCH=%s
QUAGGA_BIN_SEARCH=%s
QUAGGA_STATE_DIR=%s

searchforprog()
{
    prog=$1
    searchpath=$@
    ret=
    for p in $searchpath; do
        if [ -x $p/$prog ]; then
            ret=$p
            break
        fi
    done
    echo $ret
}

confcheck()
{
    CONF_DIR=`dirname $QUAGGA_CONF`
    # if /etc/quagga exists, point /etc/quagga/Quagga.conf -> CONF_DIR
    if [ "$CONF_DIR" != "/etc/quagga" ] && [ -d /etc/quagga ] && [ ! -e /etc/quagga/Quagga.conf ]; then
        ln -s $CONF_DIR/Quagga.conf /etc/quagga/Quagga.conf
    fi
    # if /etc/quagga exists, point /etc/quagga/vtysh.conf -> CONF_DIR
    if [ "$CONF_DIR" != "/etc/quagga" ] && [ -d /etc/quagga ] && [ ! -e /etc/quagga/vtysh.conf ]; then
        ln -s $CONF_DIR/vtysh.conf /etc/quagga/vtysh.conf
    fi
}

bootdaemon()
{
    QUAGGA_SBIN_DIR=$(searchforprog $1 $QUAGGA_SBIN_SEARCH)
    if [ "z$QUAGGA_SBIN_DIR" = "z" ]; then
        echo "ERROR: Quagga's '$1' daemon not found in search path:"
        echo "  $QUAGGA_SBIN_SEARCH"
        return 1
    fi

    flags=""

    if [ "$1" = "xpimd" ] && \\
        grep -E -q '^[[:space:]]*router[[:space:]]+pim6[[:space:]]*$' $QUAGGA_CONF; then
        flags="$flags -6"
    fi

    $QUAGGA_SBIN_DIR/$1 $flags -d
    if [ "$?" != "0" ]; then
        echo "ERROR: Quagga's '$1' daemon failed to start!:"
        return 1
    fi
}

bootquagga()
{
    QUAGGA_BIN_DIR=$(searchforprog 'vtysh' $QUAGGA_BIN_SEARCH)
    if [ "z$QUAGGA_BIN_DIR" = "z" ]; then
        echo "ERROR: Quagga's 'vtysh' program not found in search path:"
        echo "  $QUAGGA_BIN_SEARCH"
        return 1
    fi

    # fix /var/run/quagga permissions
    id -u quagga 2>/dev/null >/dev/null
    if [ "$?" = "0" ]; then
        chown quagga $QUAGGA_STATE_DIR
    fi

    bootdaemon "zebra"
    for r in rip ripng ospf6 ospf bgp babel; do
        if grep -q "^router \<${r}\>" $QUAGGA_CONF; then
            bootdaemon "${r}d"
        fi
    done

    if grep -E -q '^[[:space:]]*router[[:space:]]+pim6?[[:space:]]*$' $QUAGGA_CONF; then
        bootdaemon "xpimd"
    fi

    $QUAGGA_BIN_DIR/vtysh -b
}

if [ "$1" != "zebra" ]; then
    echo "WARNING: '$1': all Quagga daemons are launched by the 'zebra' service!"
    exit 1
fi
confcheck
bootquagga
""" % (
            cls.configs[0],
            quagga_sbin_search,
            quagga_bin_search,
            constants.QUAGGA_STATE_DIR,
        )


class QuaggaService(CoreService):
    """
    Parent class for Quagga services. Defines properties and methods
    common to Quagga's routing daemons.
    """

    name = None
    group = "Quagga"
    dependencies = ("zebra",)
    dirs = ()
    configs = ()
    startup = ()
    shutdown = ()
    meta = "The config file for this service can be found in the Zebra service."

    ipv4_routing = False
    ipv6_routing = False

    @staticmethod
    def routerid(node):
        """
        Helper to return the first IPv4 address of a node as its router ID.
        """
        for ifc in node.netifs():
            if hasattr(ifc, "control") and ifc.control is True:
                continue
            for a in ifc.addrlist:
                if a.find(".") >= 0:
                    return a.split("/")[0]
        # raise ValueError,  "no IPv4 address found for router ID"
        return "0.0.0.0"

    @staticmethod
    def rj45check(ifc):
        """
        Helper to detect whether interface is connected an external RJ45
        link.
        """
        if ifc.net:
            for peerifc in ifc.net.netifs():
                if peerifc == ifc:
                    continue
                if nodeutils.is_node(peerifc, NodeTypes.RJ45):
                    return True
        return False

    @classmethod
    def generate_config(cls, node, filename):
        return ""

    @classmethod
    def generatequaggaifcconfig(cls, node, ifc):
        return ""

    @classmethod
    def generatequaggaconfig(cls, node):
        return ""


class Ospfv2(QuaggaService):
    """
    The OSPFv2 service provides IPv4 routing for wired networks. It does
    not build its own configuration file but has hooks for adding to the
    unified Quagga.conf file.
    """

    name = "OSPFv2"
    startup = ()
    shutdown = ("killall ospfd",)
    validate = ("pidof ospfd",)
    ipv4_routing = True

    @staticmethod
    def mtucheck(ifc):
        """
        Helper to detect MTU mismatch and add the appropriate OSPF
        mtu-ignore command. This is needed when e.g. a node is linked via a
        GreTap device.
        """
        if ifc.mtu != 1500:
            # a workaround for PhysicalNode GreTap, which has no knowledge of
            # the other nodes/nets
            return "  ip ospf mtu-ignore\n"
        if not ifc.net:
            return ""
        for i in ifc.net.netifs():
            if i.mtu != ifc.mtu:
                return "  ip ospf mtu-ignore\n"
        return ""

    @staticmethod
    def ptpcheck(ifc):
        """
        Helper to detect whether interface is connected to a notional
        point-to-point link.
        """
        if nodeutils.is_node(ifc.net, NodeTypes.PEER_TO_PEER):
            return "  ip ospf network point-to-point\n"
        return ""

    @classmethod
    def generatequaggaconfig(cls, node):
        cfg = "router ospf\n"
        rtrid = cls.routerid(node)
        cfg += "  router-id %s\n" % rtrid
        # network 10.0.0.0/24 area 0
        for ifc in node.netifs():
            if hasattr(ifc, "control") and ifc.control is True:
                continue
            for a in ifc.addrlist:
                if a.find(".") < 0:
                    continue
                net = ipaddress.Ipv4Prefix(a)
                cfg += "  network %s area 0\n" % net
        cfg += "!\n"
        return cfg

    @classmethod
    def generatequaggaifcconfig(cls, node, ifc):
        return cls.mtucheck(ifc)
        # cfg = cls.mtucheck(ifc)
        # external RJ45 connections will use default OSPF timers
        # if cls.rj45check(ifc):
        #    return cfg
        # cfg += cls.ptpcheck(ifc)

        # return cfg + """\


# ip ospf hello-interval 2
#  ip ospf dead-interval 6
#  ip ospf retransmit-interval 5
# """


class Ospfv3(QuaggaService):
    """
    The OSPFv3 service provides IPv6 routing for wired networks. It does
    not build its own configuration file but has hooks for adding to the
    unified Quagga.conf file.
    """

    name = "OSPFv3"
    startup = ()
    shutdown = ("killall ospf6d",)
    validate = ("pidof ospf6d",)
    ipv4_routing = True
    ipv6_routing = True

    @staticmethod
    def minmtu(ifc):
        """
        Helper to discover the minimum MTU of interfaces linked with the
        given interface.
        """
        mtu = ifc.mtu
        if not ifc.net:
            return mtu
        for i in ifc.net.netifs():
            if i.mtu < mtu:
                mtu = i.mtu
        return mtu

    @classmethod
    def mtucheck(cls, ifc):
        """
        Helper to detect MTU mismatch and add the appropriate OSPFv3
        ifmtu command. This is needed when e.g. a node is linked via a
        GreTap device.
        """
        minmtu = cls.minmtu(ifc)
        if minmtu < ifc.mtu:
            return "  ipv6 ospf6 ifmtu %d\n" % minmtu
        else:
            return ""

    @staticmethod
    def ptpcheck(ifc):
        """
        Helper to detect whether interface is connected to a notional
        point-to-point link.
        """
        if nodeutils.is_node(ifc.net, NodeTypes.PEER_TO_PEER):
            return "  ipv6 ospf6 network point-to-point\n"
        return ""

    @classmethod
    def generatequaggaconfig(cls, node):
        cfg = "router ospf6\n"
        rtrid = cls.routerid(node)
        cfg += "  router-id %s\n" % rtrid
        for ifc in node.netifs():
            if hasattr(ifc, "control") and ifc.control is True:
                continue
            cfg += "  interface %s area 0.0.0.0\n" % ifc.name
        cfg += "!\n"
        return cfg

    @classmethod
    def generatequaggaifcconfig(cls, node, ifc):
        return cls.mtucheck(ifc)
        # cfg = cls.mtucheck(ifc)
        # external RJ45 connections will use default OSPF timers
        # if cls.rj45check(ifc):
        #    return cfg
        # cfg += cls.ptpcheck(ifc)

        # return cfg + """\


# ipv6 ospf6 hello-interval 2
#  ipv6 ospf6 dead-interval 6
#  ipv6 ospf6 retransmit-interval 5
# """


class Ospfv3mdr(Ospfv3):
    """
    The OSPFv3 MANET Designated Router (MDR) service provides IPv6
    routing for wireless networks. It does not build its own
    configuration file but has hooks for adding to the
    unified Quagga.conf file.
    """

    name = "OSPFv3MDR"
    ipv4_routing = True

    @classmethod
    def generatequaggaifcconfig(cls, node, ifc):
        cfg = cls.mtucheck(ifc)
        # Uncomment the following line to use Address Family Translation for IPv4
        cfg += "  ipv6 ospf6 instance-id 65\n"
        if ifc.net is not None and nodeutils.is_node(
            ifc.net, (NodeTypes.WIRELESS_LAN, NodeTypes.EMANE)
        ):
            return (
                cfg
                + """\
  ipv6 ospf6 hello-interval 2
  ipv6 ospf6 dead-interval 6
  ipv6 ospf6 retransmit-interval 5
  ipv6 ospf6 network manet-designated-router
  ipv6 ospf6 diffhellos
  ipv6 ospf6 adjacencyconnectivity uniconnected
  ipv6 ospf6 lsafullness mincostlsa
"""
            )
        else:
            return cfg


class Bgp(QuaggaService):
    """
    The BGP service provides interdomain routing.
    Peers must be manually configured, with a full mesh for those
    having the same AS number.
    """

    name = "BGP"
    startup = ()
    shutdown = ("killall bgpd",)
    validate = ("pidof bgpd",)
    custom_needed = True
    ipv4_routing = True
    ipv6_routing = True

    @classmethod
    def generatequaggaconfig(cls, node):
        cfg = "!\n! BGP configuration\n!\n"
        cfg += "! You should configure the AS number below,\n"
        cfg += "! along with this router's peers.\n!\n"
        cfg += "router bgp %s\n" % node.id
        rtrid = cls.routerid(node)
        cfg += "  bgp router-id %s\n" % rtrid
        cfg += "  redistribute connected\n"
        cfg += "! neighbor 1.2.3.4 remote-as 555\n!\n"
        return cfg


class Rip(QuaggaService):
    """
    The RIP service provides IPv4 routing for wired networks.
    """

    name = "RIP"
    startup = ()
    shutdown = ("killall ripd",)
    validate = ("pidof ripd",)
    ipv4_routing = True

    @classmethod
    def generatequaggaconfig(cls, node):
        cfg = """\
router rip
  redistribute static
  redistribute connected
  redistribute ospf
  network 0.0.0.0/0
!
"""
        return cfg


class Ripng(QuaggaService):
    """
    The RIP NG service provides IPv6 routing for wired networks.
    """

    name = "RIPNG"
    startup = ()
    shutdown = ("killall ripngd",)
    validate = ("pidof ripngd",)
    ipv6_routing = True

    @classmethod
    def generatequaggaconfig(cls, node):
        cfg = """\
router ripng
  redistribute static
  redistribute connected
  redistribute ospf6
  network ::/0
!
"""
        return cfg


class Babel(QuaggaService):
    """
    The Babel service provides a loop-avoiding distance-vector routing
    protocol for IPv6 and IPv4 with fast convergence properties.
    """

    name = "Babel"
    startup = ()
    shutdown = ("killall babeld",)
    validate = ("pidof babeld",)
    ipv6_routing = True

    @classmethod
    def generatequaggaconfig(cls, node):
        cfg = "router babel\n"
        for ifc in node.netifs():
            if hasattr(ifc, "control") and ifc.control is True:
                continue
            cfg += "  network %s\n" % ifc.name
        cfg += "  redistribute static\n  redistribute connected\n"
        return cfg

    @classmethod
    def generatequaggaifcconfig(cls, node, ifc):
        if ifc.net and ifc.net.linktype == LinkTypes.WIRELESS.value:
            return "  babel wireless\n  no babel split-horizon\n"
        else:
            return "  babel wired\n  babel split-horizon\n"


class Xpimd(QuaggaService):
    """
    PIM multicast routing based on XORP.
    """

    name = "Xpimd"
    startup = ()
    shutdown = ("killall xpimd",)
    validate = ("pidof xpimd",)
    ipv4_routing = True

    @classmethod
    def generatequaggaconfig(cls, node):
        ifname = "eth0"
        for ifc in node.netifs():
            if ifc.name != "lo":
                ifname = ifc.name
                break
        cfg = "router mfea\n!\n"
        cfg += "router igmp\n!\n"
        cfg += "router pim\n"
        cfg += "  !ip pim rp-address 10.0.0.1\n"
        cfg += "  ip pim bsr-candidate %s\n" % ifname
        cfg += "  ip pim rp-candidate %s\n" % ifname
        cfg += "  !ip pim spt-threshold interval 10 bytes 80000\n"
        return cfg

    @classmethod
    def generatequaggaifcconfig(cls, node, ifc):
        return "  ip mfea\n  ip igmp\n  ip pim\n"
