#!/usr/bin/python
# -*- coding: utf-8 -*-

import re

from common.driver_handler_base import DriverHandlerBase
from common.helper.system_helper import get_file_folder
from common.resource_info import ResourceInfo
from common.configuration_parser import ConfigurationParser


class GlimmerglassDriverHandler(DriverHandlerBase):
    def __init__(self):
        DriverHandlerBase.__init__(self)

        self._ctag = 1
        self._switch_name = ''
        self._switch_size = 0
        self._mapping_info = dict()

        self._resource_info = None

        self._service_mode = ConfigurationParser.get("driver_variable", "service_mode")
        self._port_logical_mode = ConfigurationParser.get("driver_variable", "port_mode")
        self._custom_port_pairing = ConfigurationParser.get("driver_variable", "custom_port_pairing") or dict()
        self._login_prompt = ConfigurationParser.get("common_variable", "device_login_prompt")

    def _incr_ctag(self):
        self._ctag += 1
        return self._ctag

    def login(self, address, username, password, command_logger=None):
        ip = address
        port = None
        if ":" in address:
            address_data = address.split(":")
            ip = address_data[0]
            port = int(address_data[1])
        if self._service_mode.lower() == "tl1":
            command = 'ACT-USER::{0}:{1}::{2};'.format(username, self._ctag, password)
            command_result = self._session.connect(host=ip, username=username, password=password, command=command,
                                                   re_string=self._login_prompt, port=port)
            command_logger.info(command_result)

            if not re.search(r'COMPLD', command_result):
                command_logger.info('Didn\'t find success message, retrying ...')
                command_result = self._session.send_command(command, re_string=self._login_prompt)
                command_logger.info(command_result)
            else:
                command_logger.info('Login status: OK')

            match_result = re.search(r"<\s+(?P<host>\S+)\s+\d+", command_result, re.DOTALL)
            if match_result is not None:
                self._switch_name = match_result.groupdict()['host']
        else:
            raise Exception(self.__class__.__name__,
                            "Selected '{}' connection type is not supported".format(self._service_mode))

    def _get_device_data(self):
        device_data = dict()

        if self._service_mode.lower() == "scpi":
            pass
        elif self._service_mode.lower() == "tl1":
            command = "rtrv-system-info:::{0};".format(self._incr_ctag())
            device_data["system_info"] = self._session.send_command(command, re_string=self._prompt)

            size_match = re.search(r"LicensedPortMatrix=(?P<src>\d+)x(?P<dst>\d+)", device_data["system_info"],
                                   re.DOTALL)

            if size_match is not None:
                size_dict = size_match.groupdict()

                self._switch_size = int(size_dict["src"]) + int(size_dict["dst"])
            else:
                raise Exception(self.__class__.__name__, "Can't find 'size' parameter!")

            command = "RTRV-CFG-FIBER::all:{0};".format(self._incr_ctag())
            device_data["port_list"] = self._session.send_command(command, re_string=self._prompt)

            command = "rtrv-crs-fiber::all:{0};".format(self._incr_ctag())
            device_data["connections_map"] = self._session.send_command(command, re_string=self._prompt)
        else:
            raise Exception(self.__class__.__name__,
                            "Selected '{}' connection type is not supported".format(self._service_mode))

        return device_data

    def get_resource_description(self, address, command_logger=None):
        self._session.send_command("", re_string=self._login_prompt)
        device_data = self._get_device_data()

        self._resource_info = ResourceInfo()
        self._resource_info.set_depth(0)
        self._resource_info.set_index(1)

        self._resource_info.set_address(address)

        if self._service_mode.lower() == "tl1":
            model_info_match = re.search('SerialNumber=(?P<serial>\S+)".*SystemType=(?P<type>\S+)".*"(?P<vendor>\S+):' +
                                         'ChassisType=(?P<model>\S+)".*SoftwareActiveVersion=(?P<version>\S+)"',
                                         device_data["system_info"], re.DOTALL)

            # add chassis info
            if model_info_match is not None:
                model_info_dict = model_info_match.groupdict()

                self._resource_info.add_attribute("Vendor", model_info_dict["vendor"])
                self._resource_info.add_attribute("Type", model_info_dict["type"])
                self._resource_info.add_attribute("Version", model_info_dict["version"])
                self._resource_info.add_attribute("Model", model_info_dict["model"])

                model_name = model_info_dict["model"]

                self._resource_info.set_model_name(model_info_dict["model"])
                self._resource_info.set_serial_number(model_info_dict["serial"])
            else:
                raise Exception(self.__class__.__name__, "Can't parse model info!")

            # get port mappings and port info
            address_prefix = address + "/"
            port_map_list = device_data["connections_map"].split("\n")
            port_list = device_data['port_list'].split("\n")

            if self._port_logical_mode.lower() == "logical":
                logical_port_map = dict()
                for port_data in port_list:
                    port_info_match = re.search(r"PORTID=(?P<id>\d+).*PORTNAME=(?P<name>(IN|OUT)\d+)" +
                                                ".*PORTHEALTH=(?P<state>good|bad)", port_data, re.DOTALL)
                    if port_info_match is not None:
                        port_info_dict = port_info_match.groupdict()
                        logical_port_id = re.sub('(IN|OUT)', '', port_info_dict["name"])
                        if logical_port_id not in logical_port_map.keys():
                            logical_port_map[logical_port_id] = {}
                        if port_info_dict["state"].lower() == "good":
                            port_state = "Enable"
                        else:
                            port_state = "Disable"

                        logical_port_map[logical_port_id]['state'] = port_state

                        if 'in' in port_info_dict["name"].lower():
                            logical_port_map[logical_port_id]['in'] = logical_port_id
                        else:
                            if logical_port_id in self._custom_port_pairing.values():
                                for key, value in self._custom_port_pairing.iteritems():
                                    if value == logical_port_id and key in logical_port_map:
                                        logical_port_map[key]['out'] = logical_port_id
                            else:
                                logical_port_map[logical_port_id]['out'] = logical_port_id

                for port_id, port_data in logical_port_map.iteritems():
                    if 'in' in port_data and 'out' in port_data:
                        logical_port_map[port_id]['port_address'] = '{0}-{1}'.format(
                            logical_port_map[port_id]['in'],
                            logical_port_map[port_id]['out'])

                for port_data in port_map_list:
                    port_map_match = re.search(r"IPORTID=(?P<src_port>\d+).*IPORTNAME=(?P<src_port_name>\S+),IP.*" +
                                               "OPORTID=(?P<dst_port>\d+).*OPORTNAME=(?P<dst_port_name>\S+),OP.*",
                                               port_data, re.DOTALL)
                    if port_map_match is not None:
                        port_map_dict = port_map_match.groupdict()
                        src_logical_port_id = re.sub('(IN|OUT)', '', port_map_dict["src_port_name"])
                        dst_logical_port_id = re.sub('(IN|OUT)', '', port_map_dict["dst_port_name"])
                        if src_logical_port_id in logical_port_map.keys() \
                                and dst_logical_port_id in logical_port_map.keys():
                            self._mapping_info[dst_logical_port_id] = src_logical_port_id

                for logical_port_index, logical_port_data in logical_port_map.iteritems():
                    port_resource_info = ResourceInfo()
                    port_resource_info.set_depth(1)
                    if 'port_address' not in logical_port_data:
                        continue
                    port_resource_info.set_index(logical_port_data['port_address'])
                    port_resource_info.set_model_name(model_name)
                    if logical_port_index in self._mapping_info:
                        port_resource_info.set_mapping(address_prefix +
                                                       logical_port_map[self._mapping_info[logical_port_index]][
                                                           'port_address'])
                    port_resource_info.add_attribute("State", logical_port_data['state'])
                    port_resource_info.add_attribute("Protocol Type", 0)
                    self._resource_info.add_child(logical_port_data['port_address'], port_resource_info)
            else:
                for port_data in port_map_list:
                    port_map_match = re.search(r".*IPORTID=(?P<src_port>\d+).*IPORTNAME=(?P<src_port_name>\S*),IP.*" +
                                               "OPORTID=(?P<dst_port>\d+).*OPORTNAME=(?P<dst_port_name>\S*),OP.*",
                                               port_data, re.DOTALL)

                    if port_map_match is not None:
                        port_map_dict = port_map_match.groupdict()
                        if int(port_map_dict['src_port']) > 0 and \
                                int(port_map_dict['dst_port']) > 0:
                            src_port = port_map_dict["src_port"]
                            dst_port = port_map_dict["dst_port"]
                            # self._mapping_info[dst_port] = src_port
                            self._mapping_info[src_port] = dst_port

                for port_data in port_list:
                    port_info_match = re.search(r"PORTID=(?P<id>\d+).*PORTNAME=(?P<name>(IN|OUT)\d+)" +
                                                ".*PORTHEALTH=(?P<state>good|bad)", port_data, re.DOTALL)

                    if port_info_match is not None:
                        port_info_dict = port_info_match.groupdict()

                        port_resource_info = ResourceInfo()
                        port_resource_info.set_depth(1)

                        port_id = port_info_dict["id"]
                        port_resource_info.set_index(port_id)
                        port_resource_info.set_model_name(model_name)
                        # port_resource_info.set_name(port_info_dict["name"])

                        if port_id in self._mapping_info:
                            port_resource_info.set_mapping(address_prefix + self._mapping_info[port_id])

                        if port_info_dict["state"].lower() == "good":
                            port_resource_info.add_attribute("State", "Enable")
                        else:
                            port_resource_info.add_attribute("State", "Disable")

                        port_resource_info.add_attribute("Protocol Type", 0)

                        self._resource_info.add_child(port_info_dict["id"], port_resource_info)
        else:
            raise Exception(self.__class__.__name__,
                            "Selected '{}' connection type is not supported".format(self._service_mode))

        return self._resource_info.convert_to_xml()

    def map_uni(self, src_port, dst_port, command_logger=None):
        if self._service_mode.lower() == "tl1":
            self._session.send_command("", re_string=self._login_prompt)
            src_in_port = min(int(src_port[1]), int(dst_port[1]))

            dst_out_port = max(int(src_port[1]), int(dst_port[1]))

            if self._port_logical_mode.lower() == "logical":
                src_in_port = str(10000 + int(src_in_port.split('-')[0]))
                dst_out_port = str(20000 + int(dst_out_port.split('-')[1]))

            command = "ent-crs-fiber::{0},{1}:{2};".format(src_in_port, dst_out_port, self._incr_ctag())
            command_result = self._session.send_command(command, re_string=self._prompt)
            command_logger.info(command_result)
        else:
            raise Exception(self.__class__.__name__,
                            "Selected '{}' connection type is not supported".format(self._service_mode))

    def map_bidi(self, src_port, dst_port, command_logger=None):
        if self._service_mode.lower() == "tl1":
            self._session.send_command("", re_string=self._login_prompt)
            if self._port_logical_mode.lower() == "logical":
                source_port = str(src_port[1]).split('-')
                destination_port = str(dst_port[1]).split('-')
                src_in_port = str(10000 + int(source_port[0]))
                dst_in_port = str(10000 + int(destination_port[0]))
                src_out_port = str(20000 + int(source_port[1]))
                dst_out_port = str(20000 + int(destination_port[1]))

                command = "ent-crs-fiber::{0}&{1},{2}&{3}:{4};".format(src_in_port, dst_in_port, dst_out_port,
                                                                       src_out_port, self._incr_ctag())
                command_result = self._session.send_command(command, re_string=self._prompt)
                command_logger.info(command_result)
            else:
                raise Exception(self.__class__.__name__,
                                "Selected '{}' connection type is not supported".format(self._service_mode))

    def map_clear_to(self, src_port, dst_port, command_logger=None):
        if self._service_mode.lower() == "tl1":
            self._session.send_command("", re_string=self._login_prompt)
            src_in_port = src_port[1]
            if self._port_logical_mode.lower() == "logical":
                source_port = src_port[1].split('-')
                src_in_port = str(10000 + int(source_port[0]))

            command = "dlt-crs-fiber::{0}:{1};".format(src_in_port, self._incr_ctag())

            self._session.send_command(command, re_string=self._prompt)
        else:
            raise Exception(self.__class__.__name__,
                            "Selected '{}' connection type is not supported".format(self._service_mode))

    def map_clear(self, src_port, dst_port, command_logger=None):
        if self._service_mode.lower() == "tl1":
            self._session.send_command("", re_string=self._login_prompt)
            if self._port_logical_mode.lower() == "logical":
                source_port = src_port[1].split('-')
                destination_port = dst_port[1].split('-')
                src_in_port = str(10000 + int(source_port[0]))
                dst_in_port = str(10000 + int(destination_port[0]))

                command = "dlt-crs-fiber::{0}&{1}:{2};".format(src_in_port, dst_in_port, self._incr_ctag())

                self._session.send_command(command, re_string=self._prompt)
            else:
                self.map_clear_to(src_port, dst_port, command_logger)
        else:
            raise Exception(self.__class__.__name__,
                            "Selected '{}' connection type is not supported".format(self._service_mode))

    def set_speed_manual(self, command_logger=None):
        pass


if __name__ == '__main__':
    import sys

    from cloudshell.core.logger.qs_logger import get_qs_logger
    from common.xml_wrapper import XMLWrapper

    ConfigurationParser.set_root_folder(get_file_folder(sys.argv[0].replace("/glimmerglass/", "/")))
    gglass = GlimmerglassDriverHandler()
    plogger = get_qs_logger('Autoload', 'GlimmerGlass', 'GlimmerGlass')

    gglass.login('localhost:1023', 'admin', '********', plogger)
    result = gglass.get_resource_description('localhost:1023')
    result1 = gglass.get_resource_description('localhost:1023')
    print XMLWrapper.get_string_from_xml(result)
    print XMLWrapper.get_string_from_xml(result1)

