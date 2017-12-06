import asyncore
import json
import parser
import socket
import traceback
import sys
from message import Message, IntroMessage
from server import Server
import struct


class Address(object):
    def __init__(self, uuid, port, hostname, server):
        """Wrapper around uuid, port, server

        Args:
            uuid (int)
            port (int)
            server (bool): False if client
        """
        self._id = uuid
        self._port = port
        self._server = server
        self._hostname = hostname

    @property
    def id(self):
        return self._id

    @property
    def port(self):
        return self._port

    @property
    def server(self):
        return self._server

    @property
    def hostname(self):
        return self._hostname


class MessagingService(asyncore.dispatcher):
    def __init__(self, addresses, server):
        """Binds to a port and listens for connections.

        Args:
            addresses (list[Address]): contains id, port, (server or client)
            server (Server): either a client or server
        """
        # Setup and bind to a port
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        print "Binding to port: {}".format(server.port)
        self.bind((server.hostname, server.port))
        self.listen(5)

        # split out clients and servers
        self._server_addresses = [addr for addr in addresses if addr.server]
        self._addresses = addresses
        self._server = server

        self._sockets = {}
        for addr in self._server_addresses:
            if addr.server and addr.port < server.port:
                print "Trying to connect to: {}:{}".format(
                        addr.hostname, addr.port)
                self.add_socket(Socket(
                        server, self, (addr.hostname, addr.port)), addr.id)

    def send(self, message, destination_id):
        """Send message to destination

        Args:
            message (Message)
            destination_id (int)
        """
        # Open new socket if necessary
        print "Finding {}".format(destination_id)
        if destination_id not in self._sockets:
            for addr in self._addresses:
                if addr.id == destination_id:
                    print "Tryna connect to: {} {} {}".format(addr.hostname, addr.port, addr.id)
                    self.add_socket(Socket(
                        self._server, self, (addr.hostname, addr.port),
                        addr.id))
        print "Sending a message to: {}".format(destination_id)
        print "Sent: {}".format(message)
        length = len(message.to_json())
        self._sockets[destination_id].send(struct.pack('!I', length))
        self._sockets[destination_id].send(message.to_json())

    def broadcast(self, message):
        """Send message to all servers

        Args:
            message (Message)
        """
        for server in self._server_addresses:
            if server.id != self._server.id:
                self.send(message, server.id)

    def handle_accept(self):
        """Opens a connection"""
        pair = self.accept()
        if pair is not None:
            sock, addr = pair
            print 'Incoming connection from %s' % repr(pair)
            s = Socket(self._server, self, sock=sock)
            print "Connection handled!"
            #s.send("Accepted connection from: {}".format(addr))
            #s.send("We did it!")

    def add_socket(self, s, uuid):
        """Adds a socket under uuid.

        Args:
            s (Socket)
            uuid (int): id of the destination
        """
        print "Adding socket: {}".format(uuid)
        self._sockets[uuid] = s


class Socket(asyncore.dispatcher_with_send):
    """Two-way connection between server and client / server

    Args:
        addr (int): ip address
        sock (socket)
        server (Server): Server who owns the MessagingService
        messaging_service (MessagingService): parent who owns this
    """
    def __init__(self, server, messaging_service, addr=None, sock=None):
        if sock is not None:
            asyncore.dispatcher_with_send.__init__(self, sock)
        else:
            asyncore.dispatcher_with_send.__init__(self)
            self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
            self.connect(addr)
        self._server = server
        self._messaging_service = messaging_service
        self._next_segment_length = 0

    def handle_read(self):
        """Receives data"""
        print "Handle_read"

        if self._next_segment_length:
            data = self.recv(self._next_segment_length)
            self._next_segment_length = 0
        else:
            data = self.recv(4)
            self._next_segment_length, = struct.unpack('!I', data)
            return

        if not data:
            return
        msg = Message.from_json(json.loads(data))
        print "Received: {}".format(msg.to_json())
        if isinstance(msg, IntroMessage):
            self._messaging_service.add_socket(self, msg.id)
        else:
            print "Sending to server to handle!"
            self._server.handle_message(msg)

    def handle_connect(self):
        print "handle_connect"
        print IntroMessage(self._server.id).to_json()
        print "Sending: {}".format(IntroMessage(self._server.id).to_json())

        length = len(IntroMessage(self._server.id).to_json())
        self.send(struct.pack('!I', length))
        self.send(IntroMessage(self._server.id).to_json())

    def handle_error(self):
        traceback.print_exc(sys.stderr)
        self.close()


if __name__ == "__main__":
    import argparse
    import time

    PORTS = [8001, 8002, 8003, 8004, 8005, 8006, 8007]
    ADDRESSES = [Address(port - 8001, port, 'localhost', True) for
                 port in PORTS]
    parser = argparse.ArgumentParser()
    parser.add_argument("port_index", type=int)
    args = parser.parse_args()
    server = Server(args.port_index)
