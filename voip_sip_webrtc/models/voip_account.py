# -*- coding: utf-8 -*-
import socket
import logging
from openerp.exceptions import UserError
_logger = logging.getLogger(__name__)
l = logging.getLogger("pydub.converter")
l.setLevel(logging.DEBUG)
l.addHandler(logging.StreamHandler())
from openerp.http import request
import re
import hashlib
import random
from openerp import api, fields, models
import threading
import time
import struct
import base64

try:
    from pydub import AudioSegment
except Exception as e:
    _logger.error(e)
            
class VoipAccount(models.Model):

    _name = "voip.account"
    _rec_name = "address"

    type = fields.Selection([('sip', 'SIP'), ('xmpp', 'XMPP')], default="sip", string="Account type")
    address = fields.Char(string="SIP Address")
    password = fields.Char(string="SIP Password")
    auth_username = fields.Char(string="Auth Username")
    username = fields.Char(string="Username")
    domain = fields.Char(string="Domain")
    outbound_proxy = fields.Char(string="Outbound Proxy")
    verified = fields.Boolean(string="Verified")
    wss = fields.Char(string="WSS", default="wss://edge.sip.onsip.com")
    
    @api.onchange('address')
    def _onchange_address(self):
        if self.address:
            if "@" in self.address:
                self.username = self.address.split("@")[0]
                self.domain = self.address.split("@")[1]

    def H(self, data):
        return hashlib.md5(data).hexdigest()

    def KD(self, secret, data):
        return self.H(secret + ":" + data)

    def rtp_server_listener(self, port):
        
        try:

            _logger.error("Start RTP Listening on Port " + str(port) )
                
            rtpsocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rtpsocket.bind(('', port));

            stage = "LISTEN"
            hex_string = ""
            joined_payload = ""
            packet_count = 0
            while stage == "LISTEN":


                rtpsocket.settimeout(10)
                data, addr = rtpsocket.recvfrom(2048)
                
                d = ['FF']
                #TODO make loop stop when BYE is received on other port

                #Convert to hex so we can human interpret each byte
                for rtp_char in data:
                    hex_format = "{0:02x}".format(ord(rtp_char))
                    d.append(hex_format)

                payload = ' '.join(d[13:])
                joined_payload += payload + " "
                packet_count += 1
                
                #only inspect every 100th packet otherwise we would flood the log file
                if packet_count % 100 == 0:
                    payload_type = int(d[2])
                    _logger.error("payload type: " + str(payload_type) )
                
                    sequence_number = int( d[3] + d[4], 16)
                    _logger.error("sequence number: " + str(sequence_number) )
                    
                    timestamp = int( d[5] + d[6] + d[7] + d[8], 32)
                    _logger.error("timestamp: " + str(timestamp) )
                    
                    synchronization_source_identifier = int( d[9] + d[10] + d[11] + d[12], 32)

                    _logger.error("synchronization source identifier: " + str(synchronization_source_identifier) )
                    _logger.error("payload length: " + str(len(payload)) )
                    _logger.error("payload: " + str(payload) )

                #For testing we only need a small amount of data
                if packet_count > 300:
                    break
                
                #rtp_data = ""

                #---- Compose RTP packet to send back (TODO) ---
                #10.. .... = Version: RFC 1889 Version (2)
                #..0. .... = Padding: False
                #...0 .... = Extension: False
                #.... 0000 = Contributing source identifiers count: 0
                #rtp_data += "80"

                #1... .... = Marker: True
                #Payload type: ITU-T G.722 (9)
                #rtp_data += " 09"

                #Sequence number: 29161
                #rtp_data += " 71 e9"

                #Timestamp: 1152425936
                #rtp_data += " 44 b0 9f d0"

                #Synchronization Source identifier: 0x1222763d (304248381)
                #rtp_data += " 12 22 76 3d"

                #Payload:
                #rtp_data += " fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa fa f7 f7 f7 f7 f7 f7 f7 f8 f7 fa f7 f8 f8 fa fa f7 f7 f8 f7 fa f8 f7 fa f8 f7 fa f7 f8 f8 fa db f0 f8 f8 f8 f8 fa 58 f1 ba 78 9e b3 9c b8 b8 f8 f1 5c f1 da b2 52 b2 5b b3 fb fa e7 cd b8 d8 55 2a b9 db b9 70 dc 9b da d7 ee 32 9c fa 58 ad 14 9b 7b 56 ea 5b ba 7c ff db b6 78 dc 7a d9 d8 ec de 78 f6 29 88 0d a4 a0 04 04 ad 36 5d 30 b1 0b b8 a3 04 bf 3b"

        except Exception as e:
            _logger.error(e)

        try:
            _logger.error("packet count: " + str(packet_count) )
            _logger.error("payload length: " + str(len(joined_payload)) )
            _logger.error("Write payload to file")
            f = open('/odoo/mygsmcall.gsm', 'w')
            f.write( joined_payload.replace(" ","").decode('hex') )
            f.close()
        except Exception as e:
            _logger.error(e)

    def test_audio_transcode(self):
        try:

            seg = AudioSegment.from_file("/odoo/mygsmcall.gsm", "gsm")
            
            seg.export("/odoo/export.mp3", format="mp3")

            #Create the call with the audio
            with api.Environment.manage():
                # As this function is in a new thread, I need to open a new cursor, because the old one may be closed
                new_cr = self.pool.cursor()
                self = self.with_env(self.env(cr=new_cr))

                with open("/odoo/export.wav", "rb") as audio_file:
                    encoded_string = base64.b64encode(audio_file.read())
                    self.env['voip.call'].create({'to_audio_filename':  time.strftime('%x') + ".mp3", 'to_audio': encoded_string })

                #Have to manually commit the new cursor?
                self.env.cr.commit()
        
                self._cr.close()

            _logger.error("Export Complete")
        except Exception as e:
            _logger.error(e)
    
    def test_sip_call(self):

        port = random.randint(6000,7000)
        media_port = random.randint(55000,56000)
        local_ip = self.env['ir.values'].get_default('voip.settings', 'server_ip')
        call_id = random.randint(50000,60000)
        from_tag = random.randint(8000000,9000000)

        rtc_listener_starter = threading.Thread(target=self.rtp_server_listener, args=(media_port,))
        rtc_listener_starter.start()

        to_address = "stevewright2009@sythiltech.onsip.com"
        #to_address = "steven@sythiltech.onsip.com"

        #----Generate SDP of audio call that the server can work with e.g. limited codex support----
        sdp = ""
        
        #Protocol Version ("v=") https://tools.ietf.org/html/rfc4566#section-5.1 (always 0 for us)
        sdp += "v=0\r\n"

        #Origin ("o=") https://tools.ietf.org/html/rfc4566#section-5.2 (Should come up with a better session id...)
        sess_id = int(time.time()) #Not perfect but I don't expect more then one call a second
        sess_version = 0 #Will always start at 0
        sdp += "o=- " + str(sess_id) + " " + str(sess_version) + " IN IP4 " + local_ip + "\r\n"
        
        #Session Name ("s=") https://tools.ietf.org/html/rfc4566#section-5.3 (We don't need a session name, information about the call is all displayed in the UI)
        sdp += "s= \r\n"
        
        #Connection Information
        #sdp += "c=IN IP4 192.168.1.133\r\n"

        #Timing ("t=") https://tools.ietf.org/html/rfc4566#section-5.9 (For now sessions are infinite but we may use this if for example a company charges a price for a fixed 30 minute consultation)        
        sdp += "t=0 0\r\n"

        #Media Descriptions ("m=") https://tools.ietf.org/html/rfc4566#section-5.14 (Message bank is audio only for now)
        audio_codec = "9" #Use G722 Audio Profile
        sdp += "m=audio " + str(media_port) + " RTP/AVP " + audio_codec + "\r\n"

        #Two way call because later we may use voice reconisation to control assistant menus        
        sdp += "a=sendrecv\r\n"

        #Hack just use X-Lite SDP (GSM)
        sdp = ""
        sdp += "v=0\r\n"
        sdp += "o=- " + str(sess_id) + " 1 IN IP4 " + local_ip + "\r\n"
        sdp += "s=X-Lite release 5.0.1 stamp 86895\r\n"
        sdp += "c=IN IP4 " + local_ip + "\r\n"
        sdp += "t=0 0\r\n"
        sdp += "m=audio " + str(media_port) + " RTP/AVP 3 101\r\n"
        sdp += "a=rtpmap:101 telephone-event/8000\r\n"
        sdp += "a=fmtp:101 0-15\r\n"
        sdp += "a=sendrecv\r\n"
         
        invite_string = ""
        invite_string += "INVITE sip:" + to_address + " SIP/2.0\r\n"
        invite_string += "Via: SIP/2.0/UDP " + local_ip + ":" + str(port) + ";branch=z9hG4bK-524287-1---0d0dce78a0c26252;rport\r\n"
        invite_string += "Max-Forwards: 70\r\n"
        invite_string += "Contact: <sip:" + self.username + "@" + local_ip + ":" + str(port) + ">\r\n"
        invite_string += 'To: <sip:' + to_address + ">\r\n"
        invite_string += 'From: "' + self.env.user.partner_id.name + '"<sip:' + self.address + ">;tag=" + str(from_tag) + "\r\n"
        invite_string += "Call-ID: " + self.env.cr.dbname + "-call-" + str(call_id) + "\r\n"
        invite_string += "CSeq: 1 INVITE\r\n"
        invite_string += "Allow: SUBSCRIBE, NOTIFY, INVITE, ACK, CANCEL, BYE, REFER, INFO, OPTIONS, MESSAGE\r\n"
        invite_string += "Content-Type: application/sdp\r\n"
        invite_string += "Supported: replaces\r\n"
        invite_string += "User-Agent: Sythil Tech Voip Client 1.0.0\r\n"
        invite_string += "Content-Length: " + str(len(sdp)) + "\r\n"
        invite_string += "\r\n"
        invite_string += sdp
         
        sipsocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sipsocket.bind(('', port));

        sipsocket.sendto(invite_string, (self.outbound_proxy, 5060) )
        
        #Wait and send back the auth reply
        stage = "WAITING"
        while stage == "WAITING":

            data, addr = sipsocket.recvfrom(2048)
 
            #Send auth response if challenged
            #_logger.error(data)
            if data.split("\r\n")[0] == "SIP/2.0 407 Proxy Authentication Required":


                #sipsocket.sendto(reply, addr)
                
                authheader = re.findall(r'Proxy-Authenticate: (.*?)\r\n', data)[0]
                         
                realm = re.findall(r'realm="(.*?)"', authheader)[0]
                method = "INVITE"
                uri = "sip:" + to_address
                nonce = re.findall(r'nonce="(.*?)"', authheader)[0]
                qop = re.findall(r'qop="(.*?)"', authheader)[0]
                nc = "00000001"
                cnonce = ''.join([random.choice('0123456789abcdef') for x in range(32)])
 
                #For now we assume qop is present (https://tools.ietf.org/html/rfc2617#section-3.2.2.1)
                A1 = self.auth_username + ":" + realm + ":" + self.password
                A2 = method + ":" + uri
                response = self.KD( self.H(A1), nonce + ":" + nc + ":" + cnonce + ":" + qop + ":" + self.H(A2) )

                reply = ""
                reply += "INVITE sip:" + to_address + " SIP/2.0\r\n"
                reply += "Via: SIP/2.0/UDP " + local_ip + ":" + str(port) + ";branch=z9hG4bK-524287-1---0d0dce78a0c26252;rport\r\n"
                reply += "Max-Forwards: 70\r\n"
                reply += "Contact: <sip:" + self.username + "@" + local_ip + ":" + str(port) + ">\r\n"
                reply += 'To: <sip:' + to_address + ">\r\n"
                reply += 'From: "' + self.env.user.partner_id.name + '"<sip:' + self.address + ">;tag=" + str(from_tag) + "\r\n"
                reply += "Call-ID: " + self.env.cr.dbname + "-call-" + str(call_id) + "\r\n"
                reply += "CSeq: 2 INVITE\r\n"
                reply += "Allow: SUBSCRIBE, NOTIFY, INVITE, ACK, CANCEL, BYE, REFER, INFO, OPTIONS, MESSAGE\r\n"
                reply += "Content-Type: application/sdp\r\n"
                reply += 'Proxy-Authorization: Digest username="' + self.auth_username + '",realm="' + realm + '",nonce="' + nonce + '",uri="sip:' + to_address + '",response="' + response + '",cnonce="' + cnonce + '",nc=' + nc + ',qop=auth,algorithm=MD5' + "\r\n"
                reply += "Supported: replaces\r\n"
                reply += "User-Agent: Sythil Tech Voip Client 1.0.0\r\n"
                reply += "Content-Length: " + str(len(sdp)) + "\r\n"
                reply += "\r\n"
                reply += sdp        
             
                sipsocket.sendto(reply, addr)
            elif data.split("\r\n")[0] == "SIP/2.0 404 Not Found":
                stage = "Not Found"
                return False
            elif data.split("\r\n")[0] == "SIP/2.0 403 Forbidden":
                #Likely means call was rejected
                stage = "Forbidden"
                return False
            elif data.startswith("BYE"):
                #Do stuff when the call is ended by client
                stage = "BYE"
                return True
            elif data.split("\r\n")[0] == "SIP/2.0 200 OK":

                contact_header = re.findall(r'Contact: <(.*?)>\r\n', data)[0]
                record_route = re.findall(r'Record-Route: (.*?)\r\n', data)[0]
                listen_media_port = int(re.findall(r'm=audio (.*?) RTP', data)[0])
        
                #Send the ACK
                reply = ""
                reply += "ACK " + contact_header + " SIP/2.0\r\n"
                reply += "Via: SIP/2.0/UDP " + local_ip + ":" + str(port) + "\r\n"
                reply += "Max-Forwards: 70\r\n"
                reply += "Route: " + record_route + "\r\n"
                reply += "Contact: <sip:" + self.username + "@" + local_ip + ":" + str(port) + ">\r\n"
                reply += 'To: <sip:' + to_address + ">;tag=fa68ca4e\r\n"
                reply += 'From: "' + self.env.user.partner_id.name + '"<sip:' + self.address + ">;tag=903df0a\r\n"
                reply += "Call-ID: " + self.env.cr.dbname + "-call-" + str(call_id) + "\r\n"
                reply += "CSeq: 1 ACK\r\n"
                reply += "User-Agent: Sythil Tech Voip Client 1.0.0\r\n"
                reply += "Content-Length: 0\r\n"
                reply += "\r\n"

                sipsocket.sendto(reply, addr)
                
                stage = "SENT"

                return True
 
    def send_simple_message(self, to_address, message_body, model=False, record_id=False):
  
        local_ip = self.env['ir.values'].get_default('voip.settings', 'server_ip')

        port = 8071

        message_string = ""
        message_string += "MESSAGE sip:" + self.domain + " SIP/2.0\r\n"
        message_string += "Via: SIP/2.0/UDP " + local_ip + ":" + str(port) + "\r\n"
        message_string += "Max-Forwards: 70\r\n"
        message_string += 'To: "' + self.env.user.partner_id.name + '"<sip:' + to_address + ">;messagetype=IM\r\n"
        message_string += 'From: "' + self.env.user.partner_id.name + '"<sip:' + self.address + ">;tag=903df0a\r\n"
        message_string += "Call-ID: 86895YTZlZGM3MzFkZTk4MzA2NGE0NjU3ZGExNmU5NTE1ZDM\r\n"
        message_string += "CSeq: 1 MESSAGE\r\n"
        message_string += "Allow: SUBSCRIBE, NOTIFY, INVITE, ACK, CANCEL, BYE, REFER, INFO, OPTIONS, MESSAGE\r\n"
        message_string += "Content-Type: text/html\r\n"
        message_string += "User-Agent: Sythil Tech Voip Client 1.0.0\r\n"
        message_string += "Content-Length: " + str(len(message_body)) + "\r\n"
        message_string += "\r\n"
        message_string += message_body

        _logger.error("MESSAGE: " + message_string)
        
        sipsocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sipsocket.bind(('', port));
        
        #Wait and send back the auth reply
        stage = "WAITING"
        while stage == "WAITING":

            sipsocket.sendto(message_string, (self.outbound_proxy, 5060) )
        
            data, addr = sipsocket.recvfrom(2048)

            #Send auth response if challenged
            _logger.error(data)
            if data.split("\r\n")[0] == "SIP/2.0 407 Proxy Authentication Required":
            
                authheader = re.findall(r'Proxy-Authenticate: (.*?)\r\n', data)[0]
                        
                realm = re.findall(r'realm="(.*?)"', authheader)[0]
                method = "MESSAGE"
                uri = "sip:" + to_address
                nonce = re.findall(r'nonce="(.*?)"', authheader)[0]
                qop = re.findall(r'qop="(.*?)"', authheader)[0]
                nc = "00000001"
                cnonce = ''.join([random.choice('0123456789abcdef') for x in range(32)])

                #For now we assume qop is present (https://tools.ietf.org/html/rfc2617#section-3.2.2.1)
                A1 = self.auth_username + ":" + realm + ":" + self.password
                A2 = method + ":" + uri
                response = self.KD( self.H(A1), nonce + ":" + nc + ":" + cnonce + ":" + qop + ":" + self.H(A2) )

                reply = ""
                reply += "MESSAGE sip:" + self.domain + " SIP/2.0\r\n"
                reply += "Via: SIP/2.0/UDP " + local_ip + ":" + str(port) + "\r\n"
                reply += "Max-Forwards: 70\r\n"
                reply += 'To: "' + self.env.user.partner_id.name + '"<sip:' + to_address + ">;messagetype=IM\r\n"
                reply += 'From: "' + self.env.user.partner_id.name + '"<sip:' + self.address + ">;tag=903df0a\r\n"
                reply += "Call-ID: 86895YTZlZGM3MzFkZTk4MzA2NGE0NjU3ZGExNmU5NTE1ZDM\r\n"
                reply += "CSeq: 2 MESSAGE\r\n"
                reply += "Allow: SUBSCRIBE, NOTIFY, INVITE, ACK, CANCEL, BYE, REFER, INFO, OPTIONS, MESSAGE\r\n"
                reply += "Content-Type: text/html\r\n"
                reply += 'Proxy-Authorization: Digest username="' + self.auth_username + '",realm="' + realm + '",nonce="' + nonce + '",uri="sip:' + to_address + '",response="' + response + '",cnonce="' + cnonce + '",nc=' + nc + ',qop=auth,algorithm=MD5' + "\r\n"
                reply += "User-Agent: Sythil Tech Voip Client 1.0.0\r\n"
                reply += "Content-Length: " + str(len(message_body)) + "\r\n"
                reply += "\r\n"
                reply += message_body
            
                sipsocket.sendto(reply, addr)
            elif data.split("\r\n")[0] == "SIP/2.0 404 Not Found":
                stage = "FAILURE"
                return False
            elif data.split("\r\n")[0] == "SIP/2.0 200 OK":
                stage = "SENT"
                
                if model:
                    #Add to the chatter
                    #TODO add SIP subtype
                    self.env[model].browse( int(record_id) ).message_post(body=message_body, subject="SIP Message Sent", message_type="comment")

                return True
                
    def send_register(self):
  
        local_ip = self.env['ir.values'].get_default('voip.settings', 'server_ip')

        register_string = ""
        register_string += "REGISTER sip:" + self.domain + " SIP/2.0\r\n"
        register_string += "Via: SIP/2.0/UDP " + local_ip + "\r\n"
        register_string += "Max-Forwards: 70\r\n"
        register_string += "Contact: <sip:" + self.username + "@" + local_ip + ":5060>\r\n" #:54443 XOR port mapping?
        register_string += 'To: "' + self.env.user.partner_id.name + '"<sip:' + self.address + ">\r\n"
        register_string += 'From: "' + self.env.user.partner_id.name + '"<sip:' + self.address + ">;tag=903df0a\r\n"
        register_string += "Call-ID: " + self.env.cr.dbname + "-account-" + str(self.id) + "\r\n"
        register_string += "CSeq: 1 REGISTER\r\n"
        register_string += "Expires: 3600\r\n"
        register_string += "Allow: SUBSCRIBE, NOTIFY, INVITE, ACK, CANCEL, BYE, REFER, INFO, OPTIONS, MESSAGE\r\n"
        register_string += "User-Agent: Sythil Tech Voip Client 1.0.0\r\n"
        register_string += "Content-Length: 0\r\n"
        register_string += "\r\n"

        _logger.error("REGISTER: " + register_string)
        
        serversocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        serversocket.sendto(register_string, (self.outbound_proxy, 5060) )