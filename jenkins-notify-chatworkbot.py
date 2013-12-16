#!/usr/bin/python
# -*- coding: utf-8 -*-
#

u'''
# Jenkins notify bot on chatwork
* Jenkins上でのビルド情報を監視して、コケてたら通知します
* 加えて、コケた状態から復活したら、それも通知します

# How to use
* config.jsonを書きます
    * config.json.template群を元に作成します
* ```python jenkins-notify-chatworkbot.py &```を実行します
* 動きました。放置してください。お疲れ様です。
    * 初回起動時のみ全部通知しちゃいますが、許してください
'''

import os
import random
import re
import time
import urllib
import urllib2
import json
from xml.dom.minidom import parseString

################################################################################
###                          classes for general                             ###
################################################################################
class BuildStatus(object):
    u'''
    ビルド情報保持クラス.保存用
    '''
    def __init__(self, job_name, last_updated, last_status = ''):
        self.job_name = job_name
        self.last_updated = last_updated
        self.last_status = last_status

    def to_stored_line(self):
        u'''
        ローカルに保存する用のフォーマットで出力
        '''
        return self.job_name + ' ' + self.last_updated + ' ' + self.last_status

    @staticmethod
    def from_stored_line(line):
        u'''
        ローカルに保存してあるファイルの行のフォーマットでパースしつつBuildStatusオブジェクトを返却
        '''
        match = re.match(r'(\S*) (\S*) (\S*)', line, re.M | re.I)
        job_name = match.group(1)
        last_updated = match.group(2)
        last_status = match.group(3)
        return BuildStatus(job_name, last_updated, last_status)

    @staticmethod
    def from_jenkins_rss_latest(entry):
        u'''
        jenkinsのrssLatest APIから取得した時のフォーマット(XML)でパースしつつBuildStatusオブジェクトを返却
        '''
        title = entry.getElementsByTagName('title')[0].childNodes[0].data
        job_name = re.match(r'(\S*)', title, re.M | re.I).group(1)
        last_updated = entry.getElementsByTagName('updated')[0].childNodes[0].data
        return BuildStatus(job_name, last_updated)

class BuildInfo(object):
    u'''
    最新のビルド情報とかに使うクラス
    '''
    def __init__(self, full_display_name, job_url, is_building, status):
        self.full_display_name = full_display_name
        self.job_url = job_url
        self.is_building = is_building
        self.status = status

    @staticmethod
    def from_jenkins_job_last_build(xml):
        u'''
        jobs/hoge/lastBuildなAPIから取得した時のフォーマット(XML)でパースしつつBuildInfoオブジェクトを返却
        '''

        full_display_name = xml.getElementsByTagName('fullDisplayName')[0].childNodes[0].data
        building = xml.getElementsByTagName('building')[0].childNodes[0].data
        is_building = True if building == 'true' else False
        status = 'BUILDING' if is_building else xml.getElementsByTagName('result')[0].childNodes[0].data
        job_url = xml.getElementsByTagName('url')[0].childNodes[0].data
        return BuildInfo(full_display_name, job_url, is_building, status)

class Identity(object):
    u'''
    識別子
    '''
    def __init__(self, value):
        self.value = value
    def __eq__(self, other):
        return self.value == other.value
    def __ne__(self, other):
        return self.value != other.value

################################################################################
###                          classes for jenkins                             ###
################################################################################
class JenkinsClient(object):
    u'''
    JenkinsサーバーにアクセスするHTTPClientクラス
    '''
    def __init__(self, url):
        u'''

        :rtype : JenkinsClient
        '''
        self.url = url

    def rss_latest(self):
        u'''
        最新ビルドのrssを取得して、BuildStatusのリストで返却
        '''
        response = self.request('/rssLatest')
        xml = parseString(response)
        entries = xml.getElementsByTagName('entry')
        new_build_status = {}
        for entry in entries:
            status = BuildStatus.from_jenkins_rss_latest(entry)
            new_build_status[status.job_name] = status
        return new_build_status

    def job_last_build(self, job_name):
        u'''
        指定したjob_nameの最新ビルド情報を取得し、BuildInfoオブジェクトを返却
        '''
        response = self.request('/job/' + job_name + '/lastBuild/api/xml')
        xml = parseString(response)
        info = BuildInfo.from_jenkins_job_last_build(xml)
        return info

    def request(self, path):
        u'''
        Jenkinsの各種APIにアクセスし、レスポンスボディの文字列を返却
        '''
        conn = urllib2.urlopen(self.url + path + '?t=' + str(time.time()))
        response = conn.read()
        conn.close()
        return response

################################################################################
###                          classes for chatwork                            ###
################################################################################

class ChatworkApiToken(object):
    u'''
    '''
    def __init__(self, value):
        u'''
        :param value:
        :rtype : ChatworkApiToken
        '''
        self.value = value

class ChatworkRoom(object):
    u'''
    chatworkの部屋
    id: 部屋のID
    '''
    def __init__(self, roomId):
        u'''
        :param roomId:
        :rtype : ChatworkRoom
        '''
        self.id = roomId

class ChatworkMessageId(Identity):
    def __init__(self, value):
        Identity.__init__(self, value)

    @staticmethod
    def from_json(obj):
        r = ChatworkMessageId(obj['message_id'])
        return r

class Emoticon(object):
    u'''
    エモーティコン
    '''
    def __init__(self, value):
        u'''
        :param value:
        :rtype : Emoticon
        '''
        self.value = '(' + value + ')'

    @staticmethod
    def devil():
        u'''
        黒いやつ
        :rtype : Emoticon
        '''
        return Emoticon('devil')

    @staticmethod
    def clap():
        u'''
        拍手してるやつ
        :rtype : Emoticon
        '''
        return Emoticon('clap')

    @staticmethod
    def flex():
        u'''
        筋肉モリモリなやつ
        :rtype : Emoticon
        '''
        return Emoticon('flex')

    @staticmethod
    def puke():
        u'''
        ウゲーってやつ
        :rtype : Emoticon
        '''
        return Emoticon('puke')

    @staticmethod
    def roger():
        u'''
        了解！なやつ。ラジャー
        :rtype : Emoticon
        '''
        return Emoticon('roger')

class ChatworkMessageBuilder(object):
    u'''
    chatworkのchat文字列を生成するimmutable Builderクラス
    '''
    def __init__(self, ctx = None):
        u'''
        :param ctx:
        :rtype : object
        '''
        if ctx is None:
            self._info_writing = False
            self._title_writing = False
            self._text = ''
            return
        self._info_writing = ctx._info_writing
        self._title_writing = ctx._title_writing
        self._text = ctx._text

    def begin_info(self):
        u'''
        infoを開始
        '''
        if self._info_writing: raise Exception('info was started')
        r = ChatworkMessageBuilder(self)
        r._text += '[info]'
        r._info_writing = True
        return r

    def end_info(self):
        u'''
        infoを終了
        '''
        if not self._info_writing: raise Exception('info was not started.')
        r = ChatworkMessageBuilder(self)
        r._text += '[/info]'
        r._info_writing = False
        return r

    def begin_title(self):
        u'''
        titleを開始
        '''
        if self._title_writing: raise Exception('title was started')
        r = ChatworkMessageBuilder(self)
        r._text += '[title]'
        r._title_writing = True
        return r

    def end_title(self):
        u'''
        titleを終了
        '''
        if not self._info_writing: raise Exception('title was not started.')
        r = ChatworkMessageBuilder(self)
        r._text += '[/title]'
        r._title_writing = False
        return r

    def with_body(self, text):
        u'''
        chat文字列に指定したtextを含める
        '''
        r = ChatworkMessageBuilder(self)
        r._text += text
        return r

    def with_emoticon(self, emoticon):
        u'''
        chat文字列に指定したEmoticonを含める
        '''
        r = ChatworkMessageBuilder(self)
        r._text += emoticon.value
        return r

    def is_valid(self):
        u'''
        ビルド可能な状態か否かを返却
        '''
        if not (not self._info_writing and not self._title_writing): return False
        return True

    def build(self):
        u'''
        ビルドを実施し、chat用の文字列を返却
        '''
        if not self.is_valid(): raise Exception('Are you finished writing title or info?')
        return self._text

class ChatworkClient(object):
    def __init__(self, token, base_url = 'https://api.chatwork.com/v1/'):
        u'''
        :param token: ChatworkApiToken
        :rtype : ChatworkClient
        '''
        self.token = token
        self.base_url = base_url

    def send_message(self, room, message):
        u'''
        :param room: ChatworkRoom
        :param message: text
        '''
        url = self.base_url + 'rooms/' + room.id + '/messages'
        req = self._create_request(url)
        params = urllib.urlencode({'body': message.encode('utf-8')})
        response = urllib2.urlopen(req, params)
        raw_body = response.read()
        json_obj = json.loads(raw_body)
        return ChatworkMessageId.from_json(json_obj)

    def _create_request(self, url):
        req = urllib2.Request(url)
        req.add_header('X-ChatWorkToken', self.token.value)
        return req

################################################################################
###                          implements for bot                              ###
################################################################################

class JenkinsNotifyPolicy(object):
    # ビルド成功可否
    BUILD = 1
    # ビルド失敗&ビルド成功
    BUILD_FIXED = 2
    # ビルド成功時のみ
    BUILD_SUCCESS = 4

    @staticmethod
    def from_str(value):
        if value == 'build': return JenkinsNotifyPolicy.BUILD
        if value == 'build_fixed': return JenkinsNotifyPolicy.BUILD_FIXED
        if value == 'build_success': return JenkinsNotifyPolicy.BUILD_SUCCESS
        return JenkinsNotifyPolicy.BUILD

class JenkinsNotifyReport(object):
    def __init__(self, job_name, full_display_name, policy, is_success, status, link):
        u'''
        :param job_name: job名
        :param full_display_name: job名とビルド番号を含む表示名
        :param policy: JenkinsNotifyPolicy
        :param is_success: ビルドが成功したか否か
        :param status: ビルドの詳細ステータス
        :param link: ビルド情報がみれるJenkinのURL
        :rtype : JenkinsNotifyReport
        '''
        self.job_name = job_name
        self.full_display_name = full_display_name
        self.policy = policy
        self.is_success = is_success
        self.status = status
        self.link = link

class JenkinsNotifyOption(object):
    default_policy = JenkinsNotifyPolicy.BUILD_FIXED
    default_message_prefix = 'Build'
    default_success_messages = ['Jenkins Build Report']
    default_failure_messages = ['Jenkins Build Report']
    default_success_emoticon = Emoticon.clap()
    default_failure_emoticon = Emoticon.devil()
    default_success_emoticon_str = 'clap'
    default_failure_emoticon_str = 'devil'
    def __init__(self,
            job_names,
            rooms = [],
            policy=default_policy,
            message_prefix=default_message_prefix,
            success_messages=default_success_messages,
            failure_messages=default_failure_messages,
            success_emoticon=default_success_emoticon,
            failure_emoticon=default_failure_emoticon):
        u'''
        :param job_names:
        :param rooms:
        :param policy:
        :param message_prefix:
        :param success_messages: 
        :param failure_messages: 
        :param success_emotion: 
        :param failure_emoticon: 
        :rtype : JenkinsNotifyOption
        '''
        self.job_names = job_names
        self.rooms = rooms
        self.policy = policy
        self.message_prefix = message_prefix
        self.success_messages = success_messages
        self.failure_messages = failure_messages
        self.success_emoticon = success_emoticon
        self.failure_emoticon = failure_emoticon

    @staticmethod
    def from_json(obj):
        jobs = obj['jobs']
        rooms = []
        for room_id in obj['rooms']: rooms.append(ChatworkRoom(room_id))
        policy = JenkinsNotifyPolicy.from_str(obj.get('policy', 'build_fixed'))
        message_prefix = obj.get('message_prefix', JenkinsNotifyOption.default_message_prefix)
        success_messages = obj.get('success_messages', JenkinsNotifyOption.default_success_messages)
        failure_messages = obj.get('failure_messages', JenkinsNotifyOption.default_failure_messages)
        success_emoticon = Emoticon(obj.get('success_emoticon', JenkinsNotifyOption.default_success_emoticon_str))
        failure_emoticon = Emoticon(obj.get('failure_emoticon', JenkinsNotifyOption.default_failure_emoticon_str))
        return JenkinsNotifyOption(
            jobs,
            rooms,
            policy,
            message_prefix,
            success_messages,
            failure_messages,
            success_emoticon,
            failure_emoticon
        )

class JenkinsNotifyConfig(object):
    u'''
    JenkinNotifyBotのConfiguration
    '''
    default_last_build_status_path = 'last_build_status.txt'
    default_interval = 120
    default_notify_options = []
    def __init__(self, api_token, jenkins_server_url, last_build_status_path, interval, notify_options):
        self.api_token = api_token
        self.jenkins_server_url = jenkins_server_url
        self.last_build_status_path = last_build_status_path
        self.interval = interval
        self.notify_options = notify_options

    @staticmethod
    def from_file(path = 'config.json'):
        u'''
        configファイルからJenkinsNotifyConfigオブジェクトを生成して返却
        '''
        last_build_status = {}
        lines = ''
        if os.path.exists(path):
            with open(path, 'r') as f: lines = f.readlines()
        conf_text = "".join(lines)
        conf_obj = json.loads(conf_text)
        api_token = ChatworkApiToken(conf_obj['api_token'])
        jenkins_server_url = conf_obj['jenkins_server_url']
        last_build_status_path = conf_obj.get('last_build_status_path', JenkinsNotifyConfig.default_last_build_status_path)
        interval = conf_obj.get('interval', JenkinsNotifyConfig.default_interval)
        options_json = conf_obj.get('notify_options', [])
        options = []
        for option_json in options_json:
            options.append(JenkinsNotifyOption.from_json(option_json))
        return JenkinsNotifyConfig(api_token, jenkins_server_url, last_build_status_path, interval, options)

class JenkinsNotifyBot(object):
    def __init__(self, config):
        u'''
        :param config:
        :rtype : JenkinsNotifyBot
        '''
        self._chatwork = ChatworkClient(config.api_token)
        self._jenkins = JenkinsClient(config.jenkins_server_url)
        self._config = config

    def run(self):
        while True:
            self._process()
            time.sleep(self._config.interval)

    def _process(self):
        u'''
        JenkinsNotifyBotのお仕事
        1. 最新ビルドが更新されてるかチェック
        2. されてたら最新情報を取得
        3. 最新ビルドがコケてたら通知
        4. コケてた状態から最新ビルドで復帰したら、通知
        5. デプロイ通知したいjobがあったら、最新ビルドが更新されてたら毎度通知
        '''
        last_build_status = self._read_last_build_status()
        new_build_status = self._jenkins.rss_latest()
        build_status_for_save = {}
        reports = []
        for job_name, build_status in new_build_status.iteritems():
            # new jobs!
            if not (job_name in last_build_status):
                last_build_status[job_name] = BuildStatus(job_name, 'new', 'FAILURE')

            # non-update
            if build_status.last_updated == last_build_status[job_name].last_updated:
                build_status_for_save[job_name] = last_build_status[job_name]
                continue

            # updated!
            build_info = self._jenkins.job_last_build(job_name)

            # continue if building now
            if build_info.is_building:
                build_status_for_save[job_name] = last_build_status[job_name]
                continue

            # detect build condition
            is_new_build_success, is_new_build_failure, is_build_fixed = self._detect_build_condition(last_build_status[job_name].last_status, build_info.status)
            print job_name, 'new_build_success:' + str(is_new_build_success), 'build_fixed:' + str(is_build_fixed)

            # report for build
            reports.append(
                JenkinsNotifyReport(
                    job_name,
                    build_info.full_display_name,
                    JenkinsNotifyPolicy.BUILD,
                    is_new_build_success,
                    build_info.status,
                    build_info.job_url
                )
            )

            # report for build_fixed
            is_notify_build = (is_new_build_failure or is_build_fixed)
            if is_notify_build:
                reports.append(
                    JenkinsNotifyReport(
                        job_name,
                        build_info.full_display_name,
                        JenkinsNotifyPolicy.BUILD_FIXED,
                        is_build_fixed,
                        build_info.status,
                        build_info.job_url
                    )
                )

            # report for build_success
            if is_new_build_success:
                reports.append(
                    JenkinsNotifyReport(
                        job_name,
                        build_info.full_display_name,
                        JenkinsNotifyPolicy.BUILD_SUCCESS,
                        is_new_build_success,
                        build_info.status,
                        build_info.job_url
                    )
                )

            # hold new status
            build_status.last_status = build_info.status
            build_status_for_save[job_name] = build_status

        self._notify_reports(reports, self._config.notify_options)
        self._write_last_build_status(build_status_for_save)

    def _detect_build_condition(self, last_status, new_status):
        is_new_build_success = (new_status == 'SUCCESS')
        is_new_build_failure = (new_status == 'FAILURE' or new_status == 'UNSTABLE')
        is_build_fixed = (
                (
                    last_status == 'FAILURE'
                    or last_status == 'UNSTABLE'
                )
                and new_status == 'SUCCESS'
        )
        return is_new_build_success, is_new_build_failure, is_build_fixed

    def _notify_reports(self, reports, options):
        u'''

        :param reports:
        :param options:
        '''
        for option in options:
            body = ''
            is_failure_once = False
            for report in reports:
                if report.policy != option.policy: continue
                if not (report.job_name in option.job_names): continue
                emoticon = option.success_emoticon if report.is_success else option.failure_emoticon
                if not is_failure_once: is_failure_once = not report.is_success
                body += self._build_message(report.full_display_name, emoticon, option.message_prefix, report.status, report.link)
            if body == '': continue
            title = ''
            if is_failure_once:
                random.shuffle(option.failure_messages)
                title = option.failure_messages[0]
            else:
                random.shuffle(option.success_messages)
                title = option.success_messages[0]
            message = self._decorate_message(title, body)
            for room in option.rooms:
                print room.id
                print message
                print '\n'
                self._chatwork.send_message(room, message)

    def _build_message(self, job_name, emoticon, prefix, status, url):
        u'''
        メッセージを生成
        '''
        return ChatworkMessageBuilder() \
            .with_body(' ') \
            .with_emoticon(emoticon) \
            .with_body(' ') \
            .with_body(job_name) \
            .with_body(': ') \
            .with_body(prefix) \
            .with_body(' ') \
            .with_body(status) \
            .with_body(' ') \
            .with_body(url) \
            .with_body('\n') \
            .build()

    def _decorate_message(self, title, report_body):
        u'''
        infoとかtitleでくくっておしゃれにしちゃう
        '''
        if not report_body: return ''
        if report_body[-1] == '\n': report_body = report_body[:-1]
        return ChatworkMessageBuilder() \
            .begin_info() \
                .begin_title() \
                    .with_body(title) \
                .end_title() \
                .with_body(report_body) \
            .end_info() \
            .build()

    def _read_last_build_status(self):
        u'''
        保存してあるビルド情報を取得
        '''
        last_build_status = {}
        lines = ''
        if os.path.exists(self._config.last_build_status_path):
            with open(self._config.last_build_status_path, 'r') as f: lines = f.readlines()
        for line in lines:
            status = BuildStatus.from_stored_line(line)
            last_build_status[status.job_name] = status
        return last_build_status

    def _write_last_build_status(self, build_status):
        u'''
        ビルド情報を保存
        '''
        text_to_write = ''
        for build_status in build_status.itervalues():
            text_to_write += build_status.to_stored_line()
            text_to_write += '\n'
        with open(self._config.last_build_status_path, 'w+') as f: f.write(text_to_write)

################################################################################
###                               entry point                                ###
################################################################################

def main():
    JenkinsNotifyBot(JenkinsNotifyConfig.from_file()).run()

if __name__ == '__main__':
    main()
