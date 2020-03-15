import re
import socket
import time
from collections import OrderedDict

from common.cli.exceptions import SessionLoopLimitException, CommandExecutionException, SessionLoopDetectorException
from common.cli.expect_session import ActionLoopDetector
from common.cli.helper.normalize_buffer import normalize_buffer
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

    def hardware_expect(self, data_str=None, re_string='', expect_map=None, error_map=None,
                        timeout=None, retries=None, check_action_loop_detector=True, empty_loop_timeout=None,
                        **optional_args):

        """Get response form the device and compare it to expected_map, error_map and re_string patterns,
        perform actions specified in expected_map if any, and return output.
        Raise Exception if receive empty responce from device within a minute

        :param data_str: command to send
        :param re_string: expected string
        :param expect_map: dict with {re_str: action} to trigger some action on received string
        :param error_map: expected error list
        :param timeout: session timeout
        :param retries: maximal retries count
        :return:
        """

        if not expect_map:
            expect_map = OrderedDict()

        if not error_map:
            error_map = OrderedDict()

        retries = retries or self._max_loop_retries
        empty_loop_timeout = empty_loop_timeout or self._empty_loop_timeout

        if data_str is not None:
            self._clear_buffer(self._clear_buffer_timeout)

            self.logger.info('Command: {}'.format(data_str.replace(self._password, "*" * 7)))
            self.send_line(data_str)

        if re_string is None or len(re_string) == 0:
            raise Exception('ExpectSession', 'List of expected messages can\'t be empty!')

        # Loop until one of the expressions is matched or MAX_RETRIES
        # nothing is expected (usually used for exit)
        output_list = list()
        output_str = ''
        retries_count = 0
        is_correct_exit = False
        action_loop_detector = ActionLoopDetector(self._loop_detector_max_action_loops,
                                                  self._loop_detector_max_combination_length)

        while retries == 0 or retries_count < retries:

            try:
                read_buffer = self._receive(timeout)
            except socket.timeout:
                read_buffer = None

            if read_buffer:
                output_str += read_buffer
                retries_count = 0
            else:
                retries_count += 1
                time.sleep(empty_loop_timeout)
                continue

            if re.search(re_string, output_str, re.DOTALL):
                output_list.append(output_str)
                is_correct_exit = True

            for expect_string in expect_map:
                result_match = re.search(expect_string, output_str, re.DOTALL)
                if result_match:
                    output_list.append(output_str)

                    if check_action_loop_detector:
                        if action_loop_detector.loops_detected(expect_string):
                            self.logger.error('Loops detected, output_list: {}'.format(output_list))
                            raise SessionLoopDetectorException(self.__class__.__name__,
                                                               'Expected actions loops detected')
                    expect_map[expect_string](self)
                    output_str = ''
                    break

            if is_correct_exit:
                break

        if not is_correct_exit:
            self.logger.debug("Received output: {}".format("".join(output_list)))
            raise SessionLoopLimitException(self.__class__.__name__,
                                            'Session Loop limit exceeded, {} loops'.format(retries_count))

        result_output = ''.join(output_list)

        for error_string in error_map:
            result_match = re.search(error_string, result_output, re.DOTALL)
            if result_match:
                self.logger.error(result_output)
                raise CommandExecutionException('ExpectSession',
                                                'Session returned \'{}\''.format(error_map[error_string]))

        # Read buffer to the end. Useful when re_string isn't last in buffer
        result_output += self._clear_buffer(self._clear_buffer_timeout)

        result_output = normalize_buffer(result_output)
        self.logger.info(result_output.replace(self._password, "*" * 7))
        return result_output
