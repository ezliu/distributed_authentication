import abc

from message import DecryptionShareMessage
from message import GetMessage
from message import PutMessage
from message import PutAcceptMessage
from message import PutCompleteMessage
from message import GetResponseMessage
from message import LoginRequest
from message import LoginResponse
from message import EnrollRequest
from message import EnrollResponse
from lamedb import LameSecretsDB
from pake2plus.pake2plus import SPAKE2PLUS_B
from pake2plus.pake2plus import password_to_secret_B
from pake2plus.util import number_to_bytes, bytes_to_number


class StateMachine(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def handle_message(self, message):
        raise NotImplementedError()


class ClientPutStateMachine(object):
    def __init__(self, enroll_request, server):
        self._responses = []
        self._server = server
        self._enroll_request = enroll_request

        # Generate Serverside Pake2+ secret
        pi_0, c = password_to_secret_B(enroll_request.password.encode('utf-8'))

        pi_0_str = str(number_to_bytes(pi_0, 2 ** (256) - 1))
        pi_0_str += c

        put = PutMessage(
            enroll_request.username, pi_0_str, server.id, server.signature_service, timestamp=enroll_request.timestamp)
        server.messaging_service.broadcast(put)
        self._sent = False


    def handle_message(self, message):
        assert isinstance(message, PutCompleteMessage)

        if message.sender_id not in self._responses:
            self._responses.append(message.sender_id)

            if not self._sent and len(self._responses) >= self._server.f + 1:
                enroll_response = EnrollResponse(
                    self._enroll_request.username,
                    self._enroll_request.timestamp)
                self._server.messaging_service.send(
                        enroll_response, self._enroll_request.user_id)
                self._sent = True


class ClientGetStateMachine(object):
    def __init__(self, login_request, server):
        self._responses = {}
        self._server = server
        self._login_request = login_request
        get = GetMessage(
            login_request.username, server.id, server.signature_service,
            timestamp=login_request.timestamp)
        server.messaging_service.broadcast(get)
        self._sent = False

    def handle_message(self, message):
        assert isinstance(message, GetResponseMessage)

        if message.sender_id not in self._responses:
            self._responses[message.sender_id] = message


            # TODO: Check f + 1 SAME
            if not self._sent and len(self._responses) >= self._server.f + 1:
                # TODO: do PAKE
                pi_0_str = self._responses.values()[0].secret
                pi_0 = bytes_to_number(pi_0_str[:32])
                c = pi_0_str[32:]
                encrypted = "lol" # to check if keys are correct

                SB = SPAKE2PLUS_B((pi_0, c))
                v = SB.start()

                key = SB.finish(self._login_request.u)
                login_response = LoginResponse(
                    self._login_request.username, v,
                    encrypted, self._login_request.timestamp)
                self._server.messaging_service.send(
                        login_response, self._login_request.user_id)
                self._sent = True


class LameClientPutStateMachine(object):
    def __init__(self, enroll_request, server):
        self._responses = []
        self._server = server
        self._enroll_request = enroll_request

        # Generate Serverside Pake2+ secret
        pi_0, c = password_to_secret_B(enroll_request.password.encode('utf-8'))

        pi_0_str = str(number_to_bytes(pi_0, 2 ** (256) - 1))
        pi_0_str += c

        server.datastore.put(enroll_request.username, pi_0_str)

        enroll_response = EnrollResponse(
            self._enroll_request.username,
            self._enroll_request.timestamp)
        self._server.messaging_service.send(
            enroll_response, self._enroll_request.user_id)

    def handle_message(self, message):
        raise NotImplementedError


class LameClientGetStateMachine(object):
    def __init__(self, login_request, server):
        self._responses = {}
        self._server = server
        self._login_request = login_request

        value = server.datastore.get(login_request.username)

        pi_0_str = value
        pi_0 = bytes_to_number(pi_0_str[:32])
        c = pi_0_str[32:]
        encrypted = "lol"  # to check if keys are correct

        SB = SPAKE2PLUS_B((pi_0, c))
        v = SB.start()

        key = SB.finish(self._login_request.u)
        login_response = LoginResponse(
            self._login_request.username, v,
            encrypted, self._login_request.timestamp)
        self._server.messaging_service.send(
            login_response, self._login_request.user_id)

    def handle_message(self, message):
        raise NotImplementedError


class PutStateMachine(object):
    """State for put

    Args:
        client_msg (PutMessage)
        server (Server)
    """
    def __init__(self, client_msg, server):
        if isinstance(client_msg, PutAcceptMessage):
            client_msg = client_msg.put_msg
        assert type(client_msg) is PutMessage

        self._acceptances = []  # List[server_id]
        self._client_msg = client_msg
        self._server = server
        self._sent_accept = False
        self._sent_response = False

    def _broadcast_put_accept(self):
        put_accept_msg = PutAcceptMessage(
            self._client_msg,
            self._server.id,
            self._server.signature_service
        )
        self._server.messaging_service.broadcast(put_accept_msg)

    def _enough_accepts(self):
        return len(self._acceptances) >= (2 * self._server.f + 1)

    def _store_secret(self):
        encrypted = self._server.threshold_encryption_service.encrypt(
            self._client_msg.secret
        )
        self._server.secrets_db.put(self._client_msg.key, encrypted)

    def _send_put_complete(self):
        put_complete_msg = PutCompleteMessage(
            self._client_msg,
            self._server.id,
            self._server.signature_service
        )
        self._server.messaging_service.send(
            put_complete_msg,
            self._client_msg.client_id
        )

    def handle_message(self, message):
        assert type(message) is PutMessage or type(message) is PutAcceptMessage

        # Broadcast put_accept once
        if not self._sent_accept:
            self._broadcast_put_accept()
            self._acceptances.append(self._server.id)
            self._sent_accept = True

        if (type(message) is PutAcceptMessage and
                message.sender_id not in self._acceptances):

            self._acceptances.append(message.sender_id)

            if not self._sent_response and self._enough_accepts():
                self._store_secret()
                self._send_put_complete()
                self._sent_response = True

            # TODO Send ACK


class GetStateMachine(object):
    def __init__(self, client_msg, server):
        """State for get

        Args:
            client_msg (GetMessage): message that this is handling
            server (Server)
        """
        if isinstance(client_msg, DecryptionShareMessage):
            client_msg = client_msg.get_message

        assert isinstance(client_msg, GetMessage)

        self._sent_share = False
        self._client_msg = client_msg
        self._server = server
        self._heard_servers = []  # List of server_ids heard from
        self._decryption_shares = []  # List of decryption_shares
        self._sent_response = False

    def _broadcast_decryption_share(self):
        self._encrypted = self._server.secrets_db.get(self._client_msg.key)
        self._decryption_share = self._server.threshold_encryption_service.decrypt(
            self._encrypted
        )
        decryption_share_msg = DecryptionShareMessage(
            self._decryption_share,
            self._server.id,
            self._client_msg,
            self._server.signature_service
        )
        self._server.messaging_service.broadcast(decryption_share_msg)

    def _enough_shares(self):
        return len(self._decryption_shares) >= (2 * self._server.f + 1)

    def _send_response_message(self):
        secret = self._server.threshold_encryption_service.combine_shares(
            self._encrypted,
            self._decryption_shares,
            self._heard_servers
        )

        response_message = GetResponseMessage(
            self._client_msg,
            secret,
            self._server.id,
            self._server.signature_service
        )

        self._server.messaging_service.send(
            response_message,
            self._client_msg.client_id
        )

    def handle_message(self, message):
        assert (type(message) is GetMessage or
                type(message) is DecryptionShareMessage)

        if not self._sent_share:
            self._broadcast_decryption_share()
            self._sent_share = True

            # Add own share to share list
            self._decryption_shares.append(self._decryption_share)
            self._heard_servers.append(self._server.id)

        if isinstance(message, DecryptionShareMessage):
            if message.sender_id not in self._heard_servers:
                self._decryption_shares.append(message.decryption_share)
                self._heard_servers.append(message.sender_id)

                if not self._sent_response and self._enough_shares():
                    self._send_response_message()
                    self._sent_response = True
                    # TODO Cleanup
                # TODO Ack message


class CatchupStateMachine(object):
    def __init__(self, server):
        """State for catching up on messages that haven't been seen before

        Args:
            server (Server)
        """
        self._catching_up = False  # Can False when you hear from 2f + 1
        self._entries = []
        self._servers = []

    def catch_up(self):
        pass

    def handle_message(self, message):
        pass


if __name__ == '__main__':
    from stubs import *
    from pake2plus.util import number_to_bytes, bytes_to_number
    servers = [StubServer(i) for i in [0, 1, 2, 3, 4, 5]]

    secret = 4720180751612715235271090812360374322170044808629075413983095821158821133441
    secret = str(number_to_bytes(secret, 2 ** 256 - 1))
    secret += secret

    encrypted = servers[0].threshold_encryption_service.encrypt(secret)

    client_msg = PutMessage("brendon", secret, 5, servers[5].signature_service)
    put_state_machine = PutStateMachine(client_msg, servers[0])

    for i in xrange(1, 6):
        put_accept_msg = PutAcceptMessage(
            client_msg, i, servers[i].signature_service
        )
        put_state_machine.handle_message(put_accept_msg)

    client_msg = GetMessage("brendon", 5, servers[5].signature_service)

    get_state_machine = GetStateMachine(client_msg, servers[0])

    for i in xrange(6):
        decryption_share = servers[i].threshold_encryption_service.decrypt(encrypted)
        decryption_share_msg = DecryptionShareMessage(
            decryption_share,
            servers[i].id,
            client_msg,
            servers[i].signature_service
        )
        get_state_machine.handle_message(decryption_share_msg)
