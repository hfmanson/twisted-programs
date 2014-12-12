from twisted.internet import interfaces
from twisted.web.resource import Resource
from twisted.web import server
from zope.interface import implements

class Producer():
    implements(interfaces.IPushProducer)

    def __init__(self, request):
        self.request = request
        self.produce = True
        request.registerProducer(self, True)    

    def stopProducing(self):
        print "stopProducing"
        self.produce = False
        self.request.unregisterProducer()
        self.request.finish()

    def pauseProducing(self):
        print "pauseProducing"
        self.produce = False
        # kill immediately
        self.stopProducing()

    def resumeProducing(self):
        print "resumeProducing"
        self.produce = True

    def write(self, data = [], event = None):
        if self.produce:
            message = ""
            if event != None:
                message += "event: " + str(event) + "\n"
            for line in data:
                message += "data: " + str(line) + "\n"
#            print message
            self.request.write(message + "\n")
    

class SseResource(Resource):

    isLeaf = True
    def __init__(self):
        Resource.__init__(self)
        self.producers = []

    def connectionClosed(self, message, producer):
        print "Connection closed"
        print message
        self.producers.remove(producer)
        print self.producers

    def render_GET(self, request):
        request.setHeader("Content-Type", "text/event-stream")
        request.setHeader("Cache-Control", "no-cache")
        request.setHeader("Connection", "keep-alive")
        #request.setHeader("Access-Control-Allow-Origin", "http://localhost")
        request.setHeader("Access-Control-Allow-Origin", "*")
        # flush headers
        request.write("");
        
        print "Connection added"
        producer = Producer(request)
        self.producers.append(producer)
        print self.producers
        d = request.notifyFinish()
        d.addCallback(self.connectionClosed, producer)
        d.addErrback(self.connectionClosed, producer)
        return server.NOT_DONE_YET

    def write(self, data = [], event = None):
        for producer in self.producers:
            producer.write(data, event)

