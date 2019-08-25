from common.cli.tcp_session import TCPSession


class GGTCPSession(TCPSession):
    def __init__(self, *args, **kwargs):
        super(GGTCPSession, self).__init__(*args, **kwargs)
        self._login_prompt = None

    def connect(self, host, username, password, command=None, error_map=None, action_map=None, port=None, re_string=''):
        self._login_prompt = re_string
        return super(GGTCPSession, self).connect(host, username, password, command, error_map, action_map, port, re_string)

    def reconnect(self, re_string=''):
        return super(GGTCPSession, self).reconnect(self._login_prompt)
