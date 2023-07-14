#!/usr/bin/python

import argparse
import json
import os
import ssl
import feedparser
import re
import requests
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import uuid
from zipfile import ZipFile
from lxml import html


TTS_VOLUME_MULTIPLY = 3.0
STORY_VOLUME_MULTIPLY = 1.5
CHOOSE_STORY_NAME = "Choisis une histoire"
CHOOSE_STORY_TEXT = "Quelle histoire veux tu écouter ?"


def crop(input, dir, name):
    output = os.path.join(dir, name)
    subprocess.call(["convert", input, "-resize", "320", "-gravity", "Center",
                     "-crop", "320x240+0+0", "+repage", "-extent", "320x240", output])
    return output


def fetch_image(url, dir, name):
    print("fetch image %s" % (url,))
    filename = os.path.join(dir, os.path.basename(url))
    urllib.request.urlretrieve(url, filename)
    output = crop(filename, dir, name)
    os.unlink(filename)
    return output


def run_command(cmd):
    print(cmd)
    subprocess.call(cmd)


def fetch_media(url, dir, name):
    print("fetch media %s" % (url,))
    base, ext = os.path.splitext(url)
    output = os.path.join(dir, name+ext)
    urllib.request.urlretrieve(url, output)
    mp3 = os.path.join(dir, name + ".mp3")
    if mp3 != output:
        run_command(["ffmpeg",
                     "-i", output,
                     "-n",
                     "-vn", "-ac", "1", "-acodec",
                     "copy", "-filter:a",
                     "volume="+str(STORY_VOLUME_MULTIPLY),
                     # "-c:a", "libvorbis", ogg])
                     # "-ar", "44100",
                     "-c:a", "libmp3lame", "-b:a", "128k", mp3])
        os.unlink(output)
    return mp3


def say(sentence, dir, name):
    wav = os.path.join(dir, name+".wav")
    run_command(["pico2wave", "-l", "fr-FR", "-w", wav, sentence])
    mp3 = os.path.join(dir, name + ".mp3")
    run_command(["ffmpeg",
                     "-i", wav,
                     "-n",
                     "-ac", "1",
                     "-filter:a",
                     # "-ar", "44100",
                     "adelay=1s,apad=pad_len=16384,"
                     "volume="+str(TTS_VOLUME_MULTIPLY),
                     "-c:a", "libmp3lame", "-b:a", "128k", mp3])
    os.unlink(wav)
    return mp3


class Walker:

    def __init__(self, directory):
        self.directory = directory
        node = json.load(os.path.join(directory, "node.json"))
        self.pack = {
            "format": "v1",
            "version": 1,
            "title": node["title"],
            "description": node["description"],
        }

    def load_node(self, root):
        return json.load(os.path.join(root, "node.json"))

    def generate_pack(self):
        for root, dirs, files in os.walk(self.directory, topdown=True):
            node = json.load(os.path.join(root, "node.json"))
            if node["type"] == "cover":
                pass


class Pack:
    format = "v1"
    version = 1
    name = "My pack"
    description = "My description"
    image = None
    cover = None

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            self.__dict__[k] = v

    def generate(self, output):
        tmpdir = tempfile.mkdtemp(prefix="luniipack")
        assets = os.path.join(tmpdir, "assets")
        os.mkdir(assets)

        with ZipFile(output, "w") as packzip:
            packzip.write(assets, "assets")

            if self.image:
                packzip.write(crop(self.image, tmpdir, "thumbnail.png"),
                              "thumbnail.png")

            for node in self.cover.get_nodes():
                if node.image:
                    name, ext = os.path.splitext(node.image)
                    asset = node.id+ext
                    packzip.write(node.image, arcname="assets/"+asset)
                    node.image = asset
                if node.audio:
                    name, ext = os.path.splitext(node.audio)
                    asset = node.id+ext
                    packzip.write(node.audio, arcname="assets/"+asset)
                    node.audio = asset

            packzip.writestr("story.json", json.dumps(self.json()))
            print(json.dumps(self.json()))

    def json(self):
        if not self.cover:
            raise Exception("Pack has no cover item")

        actionNodes = [action.json() for action in self.cover.get_actions()]
        stageNodes = [node.json() for node in self.cover.get_nodes()]

        return {
            "format": self.format,
            "title": self.name,
            "version": self.version,
            "description": self.description,
            "stageNodes": stageNodes,
            "actionNodes": actionNodes
        }


class ControlSettings:
    wheel = False
    ok = False
    home = False
    pause = False
    autoplay = False

    def __init_(self, kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def json(self):
        return {
            "wheel": self.wheel,
            "ok": self.ok,
            "home": self.home,
            "pause": self.pause,
            "autoplay": self.autoplay
        }


class Node:
    type = ""
    name = ""
    id = ""
    audio = None
    image = None
    home_action = None
    group_id = ""
    ok_action = None

    def __init__(self, name, **kwargs):
        self.name = name
        self.nodes = []
        self.control_settings = ControlSettings()
        for k, v in kwargs.items():
            setattr(self, k, v)
        if not self.id:
            self.id = str(uuid.uuid4())

    def json(self):
        json = {
            "uuid": self.id,
            "type": self.type
        }

        if self.group_id:
            json["groupId"] = self.group_id

        json.update({
            "name": self.name,
            "position": {
                "x": 100,
                "y": 100
            },
            "image": self.image,
            "audio": self.audio
        })

        if self.ok_action:
            json["okTransition"] = {
                "actionNode": self.ok_action.id,
                "optionIndex": 0,
            }
        else:
            json["okTransition"] = None

        if self.home_action:
            json["homeTransition"] = {
                "actionNode": self.home_action.id,
                "optionIndex": 0,
            }
        else:
            json["homeTransition"] = None

        json.update({
            "controlSettings": self.control_settings.json(),
        })

        return json

    def get_actions(self):
        if self.ok_action:
            return [self.ok_action]
        return []

    def get_nodes(self):
        return [self]


class Action:
    parent = None
    child = None
    options = []
    type = ""
    id = ""
    group_id = ""

    def __init__(self, type, child, options, **kwargs):
        self.type = type
        self.child = child
        self.name = child.name + "." + self.type
        self.group_id = child.group_id
        self.id = str(uuid.uuid4())
        self.options = options
        for k, v in kwargs.items():
            setattr(self, k, v)

    def json(self):
        json = {
            "id": self.id,
            "type": self.type,
            "groupId": self.group_id,
            "name": self.name,
            "options": [opt.id for opt in self.options]
        }

        if self.group_id:
            json["groupId"] = self.group_id

        return json


class Cover(Node):
    type = "cover"
    menu = None
    square_one = True

    def __init__(self, name, **kwargs):
        if "menu" in kwargs:
            self.set_menu(kwargs.pop("menu"))
        super(Cover, self).__init__(name, **kwargs)
        self.control_settings.wheel = True
        self.control_settings.ok = True

    def json(self):
        json = super(Cover, self).json()
        json["squareOne"] = self.square_one
        return json

    def set_menu(self, menu):
        self.menu = menu
        self.ok_action = Action("menu.questionaction", self.menu.question,
                                [self.menu.question])

    def get_nodes(self):
        nodes = [self]
        if self.menu:
            nodes += self.menu.get_nodes()
        return nodes

    def get_actions(self):
        actions = super(Cover, self).get_actions()
        if self.menu:
            actions += self.menu.get_actions()
        return actions


class Menu(Node):
    question = None
    options = []

    def __init__(self, question, options=[], **kwargs):
        self.options = []
        self.id = str(uuid.uuid4())
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.set_question(question)
        for option in options:
            self.add_option(option)

    def set_question(self, question):
        self.question = question
        if question:
            question.group_id = self.id
        self.question.ok_action = Action("menu.optionsaction",
                                         question, self.options)

    def add_option(self, option):
        self.options.append(option)
        option.group_id = self.id
        self.question.ok_action.options = self.options

    def get_nodes(self):
        nodes = []
        if self.question:
            nodes += self.question.get_nodes()
        for option in self.options:
            nodes += option.get_nodes()
        return nodes

    def get_actions(self):
        actions = [self.question.ok_action]
        for option in self.options:
            actions += option.get_actions()
        return actions


class Question(Node):
    type = "menu.questionstage"

    def __init__(self, name, **kwargs):
        super(Question, self).__init__(name, **kwargs)
        self.control_settings.autoplay = True


class Option(Node):
    type = "menu.optionstage"

    def __init__(self, name, **kwargs):
        super(Option, self).__init__(name, **kwargs)
        self.control_settings.wheel = True
        self.control_settings.ok = True
        self.control_settings.home = True

    def set_ok_transition(self, node):
        self.ok_action = Action(node.action_type, node, [node])

    def get_nodes(self):
        nodes = super(Option, self).get_nodes()
        if self.ok_action:
            nodes += self.ok_action.child.get_nodes()
        return nodes


class Story(Node):
    type = "story"
    action_type = "story.storyaction"

    def __init__(self, cover, **kwargs):
        super(Story, self).__init__(**kwargs)
        self.group_id = self.id
        self.ok_action = cover.ok_action
        self.home_action = cover.ok_action
        self.control_settings.autoplay = True


class Stage:
    def __init__(self):
        self.nodes = []

    def add_stage(self, stage):
        self.nodes.append(stage)


class Crawler:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp("lunii-podcast")

    def __del__(self):
        shutil.rmtree(self.tmpdir)

    def fetch_image(self, url, output):
        return fetch_image(url, self.tmpdir, output)

    def fetch_media(self, url, output):
        return fetch_media(url, self.tmpdir, output)

    def say(self, sentence, output):
        return say(sentence, self.tmpdir, output)


class RSSCrawler(Crawler):

    def generate_pack(self, url, output, filter="", title=""):
        rfilter = re.compile(filter.lower())

        feed = feedparser.parse(url)
        channel = feed['channel']

        logo = self.fetch_image(channel['image']['href'], "logo.png")

        audio = self.say("Quelle histoire veux tu écouter ?", "question")
        question = Question(name="Choisis une histoire", audio=audio)

        if not title:
            title = channel['title']
        audio = self.say(title, "title")
        menu = Menu(question=question, options=[])
        cover = Cover(title, menu=menu, audio=audio, image=logo)
        pack = Pack(name=title, cover=cover)

        stories = []
        for i, entry in enumerate(feed["entries"]):
            entry_title = entry['title']

            if filter:
                if not rfilter.match(entry_title.lower()):
                    continue

            audio = self.say(entry_title, "Title - " + entry_title)
            option = Option(name=entry_title, audio=audio, image=logo)
            menu.add_option(option)

            audio = self.fetch_media(entry['links'][-1]['href'], entry_title)
            story = Story(name=entry_title, cover=cover, audio=audio)
            stories.append(story)

            option.set_ok_transition(story)

        pack.generate(output)


class FranceInterCrawler(Crawler):

    def generate_pack(self, url, output,
                      filter="", title="", data_tag="histoire"):
        rfilter = re.compile(filter)

        page = requests.get(url)
        tree = html.fromstring(page.content)

        if not title:
            title = tree.xpath('//h1[@class="cover-emission-title"]')[0].text

        logo_img = tree.xpath('//div[@class="cover-portrait"]/img')[0]
        logo_url = logo_img.get("data-dejavu-src")
        logo = self.fetch_image(logo_url, "logo.png")

        story_xpath = '//div[@data-tag="%s"]/figure' % (data_tag,)
        stories = tree.xpath(story_xpath)

        audio = self.say(CHOOSE_STORY_TEXT, "question")
        question = Question(name=CHOOSE_STORY_NAME, audio=audio)

        audio = self.say(title, "title")
        menu = Menu(question=question, options=[])
        cover = Cover(title, menu=menu, audio=audio, image=logo)
        pack = Pack(name=title, cover=cover, description=title, image=logo)

        o = urllib.parse.urlparse(url)
        pages = tree.xpath("//li[@class='pager-item']/a")
        for other_page in pages:
            page_path = other_page.get("href")
            other_page = requests.get(o._replace(path=page_path).geturl())
            tree = html.fromstring(other_page.content)
            stories += tree.xpath(story_xpath)

        stories.reverse()
        for story in stories:
            img = story.xpath(".//picture/img")[0]
            img_url = img.get('data-dejavu-src')
            button = story.xpath(".//button")[0]
            title = button.get('data-diffusion-title')

            if filter:
                if not rfilter.match(title.lower()):
                    continue

            logo = self.fetch_image(img_url, title+"-logo.png")

            audio = self.say(title, "Title - " + title)
            option = Option(name=title, audio=audio, image=logo)
            menu.add_option(option)

            audio = self.fetch_media(button.get('data-url'), title)

            storyStep = Story(name=title, cover=cover, audio=audio)

            option.set_ok_transition(storyStep)

        pack.generate(output)


def main():
    ssl._create_default_https_context = ssl._create_unverified_context

    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--type",
                        required=True,
                        choices=["odyssees", "oli", "rss"],
                        help="crawler type")
    parser.add_argument("--output", default="pack.zip",
                        help="output file")
    parser.add_argument("--title", default="",
                        help="pack title")
    parser.add_argument("--filter", default="",
                        help="story filter")
    args = parser.parse_args()

    kwargs = dict(
        filter=args.filter,
        title=args.title,
    )

    if args.type == "oli":
        args.url = "https://www.franceinter.fr/emissions/une-histoire-et-oli"
        kwargs["data_tag"] = "culture"
        crawler = FranceInterCrawler()
    elif args.type == "odyssees":
        args.url = "https://www.franceinter.fr/emissions/les-odyssees"
        kwargs["data_tag"] = "histoire"
        crawler = FranceInterCrawler()
    elif args.type == "rss":
        crawler = RSSCrawler()

    crawler.generate_pack(args.url, args.output, **kwargs)


if __name__ == "__main__":
    main()
