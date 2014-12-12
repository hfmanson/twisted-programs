import re
from xml.etree import ElementTree
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
from twisted.web.resource import Resource
from twisted.web.server import Site
from twisted.web.static import File
import OSC

from sseresource import SseResource


class OSCDevice(object):
    def __init__(self, name, paramstr, inetaddress):
        # devicenaam
        self.name = name
        # parameter string splitsen en parameters gebruiken als key voor de variabele self.params
        paramstrarr = paramstr.split(',')
        self.params = dict()
        # beginwaarde van parameters is 0
        for param in paramstrarr:
            self.params[param] = 0
        # IP adres van device
        self.inetaddress = inetaddress

    def toXML(self):
        # device status renderen als XML document, standaard type is 'output'
        root = ElementTree.Element("device", name = self.name, ip = self.inetaddress, type = "output")
        parameters = ElementTree.SubElement(root, "parameters")
        for key, value in self.params.iteritems():
            ElementTree.SubElement(parameters, "parameter", name = key, value = str(value))
        return root

class OSCInputDevice(OSCDevice, DatagramProtocol):
    def __init__(self, name, paramstr, inetaddress):
        OSCDevice.__init__(self, name, paramstr, inetaddress)
        self.port = 7000

    def toXML(self):
        # device status renderen als XML document type is nu 'input'
        root = super(OSCInputDevice, self).toXML()
        root.set("type", "input")
        return root

    def startProtocol(self):
        # wordt aangeroepen door reactor.listenUDP()
        # UDP verbinding 'connecten'
        self.transport.connect(self.inetaddress, self.port)
        print "now we can only send to host %s port %d" % (self.inetaddress, self.port)

    def send(self, oscmsg):
#        print "send: " + str(oscmsg)
        if self.transport == None:
            # bij eerste keer zenden het protocol starten
            reactor.listenUDP(0, self)
        # OSC bericht encoderen en versturen           
        self.transport.write(oscmsg.getBinary()) # no need for address

    def setPort(self, port):
        self.port = port

# handler voor binnenkomende UDP berichten met het 'heinze' protocol
class OSCReceiver(DatagramProtocol):
    def datagramReceived(self, data, (host, port)):
#        print "received %r from %s:%d" % (data, host, port)
#        self.transport.write(data, (host, port))

        # OSC bericht decoderen en opslaan in lokale variabelen
        # bv. /csound-drone/out/inputs ,s distortfactor,harmonic,disttable,feedback
        #   address  = 'csound-drone'
        #   typetags = 's'
        #   values   = [ 'distortfactor,harmonic,disttable,feedback' ]
        decoded = OSC.decodeOSC(data)
        address = decoded[0]
        typetags = decoded[1][1:]
        values = decoded[2:]
        m = re.match(r"/(.+)/(.+)/(.+)", address)
        if m:
            inout = m.group(2)
            if inout == "out":
                name = m.group(1)
                param = m.group(3)
                value = str(values[0])
                if typetags == "s":
                    # nieuw datadirigent apparaat
                    print "received from %s:%d" % (host, port)
                    if param == "outputs":
                        oscDevice = OSCDevice(name, value, host)
                        outputDevices[name] = oscDevice
                        print ElementTree.tostring(oscDevice.toXML())
                        sse.write(event = 'AddedOutputDevice', data = [ name ])
                    elif param == "inputs":
                        oscDevice = OSCInputDevice(name, value, host)
                        inputDevices[name] = oscDevice
                        print ElementTree.tostring(oscDevice.toXML())
                        sse.write(event = 'AddedInputDevice', data = [ name ])
                elif typetags == "i":
                    # voor invoerapparaten: standaard poort (7000) wijzigen NA opgeven parameters (zie hiervoor)
                    # bv. /csound-drone/out/port ,i 7001
                    if param == "port":
                        listenport = int(value)
                        print "port is %d" % listenport
                        if name in inputDevices:
                            inputDevice = inputDevices[name]
                            inputDevice.setPort(listenport)
                elif typetags == "f":
                    # wijziging van een parameter van een uitvoerapparaat
                    if name in outputDevices:
                        outputDevice = outputDevices[name]
                        if param in outputDevice.params:
                            # waarde aanpassen in uitvoerapparaat
                            outputDevice.params[param] = value
                            # doorgeven naar browsers via SSE
                            sse.write(event = 'change', data = [ name, param, value ])
                            # gelinkte invoerapparaten updaten
                            outdevpar = (name, param)
                            if outdevpar in links:
                                outputlinks = links[outdevpar]
                                for outputlink in outputlinks:
                                    inputname = outputlink[0]
                                    inputparam = outputlink[1]
                                    # wijziging ook doorgeven aan browsers
                                    sse.write(event = "sliderchange", data = [ inputname, inputparam, value ])
                                    # OSC bericht versturen naar invoerapparaat
                                    msg = OSC.OSCMessage("/" + inputname + "/in/" + inputparam)
                                    inputdevice = inputDevices[inputname]
                                    msg.append(value, "f")
                                    inputdevice.send(msg)
                                    
# http://localhost:8811/Devices?type=output                
# http://localhost:8811/Devices?type=input
# in- of uitvoerapparaat lijst opvragen, resultaat is XML
class Devices(Resource):
    isLeaf = True
    def render_GET(self, request):
        args = request.args
        print args
        request.setHeader("Content-Type", "text/xml;charset=UTF-8")
        typ = args["type"][0] if "type" in args else "input"
        root = ElementTree.Element("devices", type = typ)
        if typ == "output":
            for oscDevice in outputDevices:
                print oscDevice
                ElementTree.SubElement(root, "device", name = oscDevice)
        elif typ == "input":
            for oscDevice in inputDevices:
                print oscDevice
                ElementTree.SubElement(root, "device", name = oscDevice)
        return ElementTree.tostring(root)

# http://localhost:8811/Devices?type=output&name=channels                
# http://localhost:8811/Devices?type=input&name=csound
# in- of uitvoerapparaat opvragen, resultaat is XML
class Device(Resource):
    isLeaf = True
    def render_GET(self, request):
        args = request.args
        print args
        request.setHeader("Content-Type", "text/xml;charset=UTF-8")
        if "name" in args and "type" in args:
            name = args["name"][0]
            typ = args["type"][0]
            if "action" in args and args["action"][0] == "delete":
                if typ == "output":
                    if name in outputDevices:
                        sse.write(event = 'DeletedOutputDevice', data = [ name ])
                        del outputDevices[name]
                elif typ == "input":
                    if name in inputDevices:
                        sse.write(event = 'DeletedInputDevice', data = [ name ])
                        del inputDevices[name]
            else:                
                if typ == "output":
                    if name in outputDevices:
                        outputDevice = outputDevices[name]
                        return ElementTree.tostring(outputDevice.toXML())
                elif typ == "input":
                    if name in inputDevices:
                        inputDevice = inputDevices[name]
                        return ElementTree.tostring(inputDevice.toXML())
        return ""
# wordt via ajax aangeroepen bij het schuiven van een slider van een invoerapparaat
# zodat de slider van de andere browsers word geupdated
# http://localhost:8811/SendOSC?address=127.0.0.1&name=csound-drone&param=distortfactor&value=0.008 
class SendOSC(Resource):
    isLeaf = True
    def render_GET(self, request):
        args = request.args
        print args
        if "name" in args and "param" in args and "value" in args:
            name = args["name"][0]
            param = args["param"][0]
            value = args["value"][0]
            # sliderchange event doorgeven aan browsers
            sse.write(event = "sliderchange", data = [ name, param, value ])
            # OSC bericht sturen naar het invoerapparaat
            if name in inputDevices:
                inputDevice = inputDevices[name]
                if param in inputDevice.params:
                    inputDevice.params[param] = value
                    msg = OSC.OSCMessage("/" + name + "/in/" + param)
                    msg.append(value, "f")
#                    print msg
                    inputDevice.send(msg)
        return ""
# link creeren:
# http://localhost:8811/OSCLink?outputdevice=channels&outputparameter=ch1&inputdevice=csound-drone&inputparameter=distortfactor
# link verwijderen:
# http://localhost:8811/OSCLink?outputdevice=channels&outputparameter=ch1&inputdevice=csound-drone&inputparameter=distortfactor&action=delete
# links opvragen:
# http://localhost:8811/OSCLink

class OSCLink(Resource):
    isLeaf = True
    def render_GET(self, request):
        args = request.args
        print args
        if "outputdevice" in args and "outputparameter" in args and "inputdevice" in args and "inputparameter" in args:
            outputdevice = args["outputdevice"][0]
            outputparameter = args["outputparameter"][0]
            inputdevice = args["inputdevice"][0]
            inputparameter = args["inputparameter"][0]
            outdevpar = (outputdevice, outputparameter)
            indevpar = (inputdevice, inputparameter)
            if "action" in args and args["action"][0] == "delete":
                sse.write(event = "DeletedLink", data = [ outputdevice, outputparameter, inputdevice, inputparameter ])
                links[outdevpar].discard(indevpar)
            else:
                if not outdevpar in links:
                    links[outdevpar] = set()
                # interessante vraag die niet interessant gevonden wordt:
                # http://stackoverflow.com/questions/4221968/any-reason-there-are-no-returned-value-from-set-add
                if not indevpar in links[outdevpar]:
                    links[outdevpar].add(indevpar)
                    sse.write(event = "AddedLink", data = [ outputdevice, outputparameter, inputdevice, inputparameter ])
        else:
            request.setHeader("Content-Type", "text/xml;charset=UTF-8")
            root = ElementTree.Element("links")
            for outkey, outvalue in links.iteritems():
                for inputvalue in outvalue:
                    ElementTree.SubElement(root, "link", outputdevice = outkey[0], outputparameter = outkey[1], inputdevice = inputvalue[0], inputparameter = inputvalue[1])
            return ElementTree.tostring(root)                
        return ""

outputDevices = dict()
inputDevices = dict()
links = dict()
oscreceiver = OSCReceiver()
# UDP poort 9999
reactor.listenUDP(9999, oscreceiver)
root = Resource()
sse = SseResource()
# urls koppelen aan Resource's
root.putChild("sse", sse)
root.putChild("page", File("osc.html"))
root.putChild("Devices", Devices())
root.putChild("Device", Device())
root.putChild("SendOSC", SendOSC())
root.putChild("OSCLink", OSCLink())
factory = Site(root)
# server draait op poort 8811
reactor.listenTCP(8811, factory)

reactor.run()
