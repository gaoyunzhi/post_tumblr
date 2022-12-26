#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import tweepy
import yaml
import time
import plain_db
import webgram
import post_2_album
from telegram_util import removeOldFiles, matchKey
import random
from bs4 import BeautifulSoup
import cached_url
import telepost

with open('credential') as f:
    credential = yaml.load(f, Loader=yaml.FullLoader)

existing = plain_db.loadLargeDB('existing', isIntValue=True)

client = pytumblr.TumblrRestClient(
    credential['consumer_key'],
    credential['consumer_secret'],
    credential['token'],
    credential['token_secret'],
)

Day = 24 * 60 * 60

def getCutoffTime(channel):
    return time.time() - credential['channels'][channel]['padding_days'] * Day

def getRawPosts(channel):
    start = time.time()
    result = []
    posts = webgram.getPosts(channel)[1:]
    result += posts
    while posts and posts[0].time > (time.time() - 
            credential['channels'][channel]['back_days'] * Day):
        pivot = posts[0].post_id
        posts = webgram.getPosts(channel, posts[0].post_id, 
            direction='before')[1:]
        result += posts
    if random.random() > 0.2:
        random.shuffle(result)
    else:
        result = result[::-1]
    return result

def getPosts(channel):
    result = getRawPosts(channel)
    cutoff_time = getCutoffTime(channel)
    for post in result:
        if post.time > cutoff_time:
            continue
        try:
            yield post_2_album.get('https://t.me/' + post.getKey()), post
        except Exception as e:
            print('post_twitter post_2_album failed', post.getKey(), str(e))

async def getMediaSingle(api, fn, post):
    try:
        return api.media_upload(fn).media_id
    except Exception as e:
        print('post_twitter media upload failed:', str(e), str(post))

async def getMedia(api, fns, post):
    result = []
    for fn in fns:
        media = await getMediaSingle(api, fn, post)
        if media:
            if fn.endswith('.mp4'): # may need to revisit
                return [media]
            result.append(media)
        if len(result) >= 4:
            return result
    return result

twitter_api_cache = {}
def getTwitterApi(channel):
    user = credential['channels'][channel]['twitter_user']
    if user in twitter_api_cache:
        return twitter_api_cache[user]
    auth = tweepy.OAuthHandler(credential['twitter_consumer_key'], credential['twitter_consumer_secret'])
    auth.set_access_token(credential['twitter_users'][user]['access_key'], credential['twitter_users'][user]['access_secret'])
    api = tweepy.API(auth)
    twitter_api_cache[user] = api
    return api

async def getMediaIds(api, channel, post, album):
    fns = await telepost.getImages(channel, post.post_id, post.getImgNumber())
    media_ids = await getMedia(api, fns, post)
    return list(media_ids)

async def post_twitter(channel, post, album, status_text):
    api = getTwitterApi(channel)
    media_ids = []
    if post.hasVideo() or album.video or album.imgs:
        media_ids = await getMediaIds(api, channel, post, album)
        if not media_ids:
            return
    try:
        return api.update_status(status=status_text, media_ids=media_ids)
    except Exception as e:
        if 'Tweet needs to be a bit shorter.' not in str(e):
            print('post_twitter send twitter status failed:', str(e), album.url)
            raise e
        

def lenOk(text):
    return sum([1 if ord(char) <= 256 else 2 for char in text]) <= 280

def cutText(text, splitter):
    if not text:
        return ''
    result = ''
    last_good = text
    for substr in text.split(splitter)[:-1]:
        result += substr + splitter
        if lenOk(result):
            last_good = result
        else:
            return last_good
    result += text.split(splitter)[-1]
    if lenOk(result):
        return text
    else:
        return last_good

def getWaitingCount(user):
    count = 0
    for channel in credential['channels']:
        if credential['channels'][channel]['twitter_user'] != user:
            continue
        for post in getRawPosts(channel):
            if existing.get('https://t.me/' + post.getKey()):
                continue
            if credential['channels'][channel].get('cut_text'):
                count += 1
                continue
            status_text = post.text and post.text.text or ''
            if not status_text:
                continue
            if sum([1 if ord(char) <= 256 else 2 for char in status_text]) + 19 <= 280:
                count += 1
    return count

def tooClose(channel):
    user = credential['channels'][channel]['twitter_user']
    api = getTwitterApi(channel)
    try:
        elapse = time.time() - api.user_timeline(user_id=user, count=1)[0].created_at.timestamp()
    except Exception as e:
        if 'this account is temporarily locked' in str(e) and random.random() < 0.01:
            print('post_twitter linked twitter for channel fetch fail', channel, user, e)
        return True
    if elapse < 60:
        return True
    if elapse > credential['channels'][channel].get('max_interval', 5 * 60) * 60:
        return False
    waiting_count = getWaitingCount(user)
    if waiting_count == 0:
        return True
    to_wait = min(60 * 60 * 1000 / waiting_count ** 2, 60 * 60 * 30 / waiting_count)
    return elapse < to_wait

def getLinkReplace(url):
    if 'telegra.ph' not in url:
        return url
    if not url.startswith('http'):
        url = 'https://' + url
    soup = BeautifulSoup(cached_url.get(url, force_cache=True), 'html.parser')
    try:
        return soup.find('address').find('a')['href']
    except:
        print('post_twitter can not find link replace', url)
        return url

async def getRawText(channel, post):
    text, post = await telepost.getRawText(channel, post.post_id)
    text = ''.join(text)
    text = '\n\n'.join([line.strip() for line in text.split('\n')]).strip()
    for _ in range(5):
        text.replace('\n\n\n', '\n\n')
    return text

async def getText(channel, post):
    text, post = await telepost.getRawText(channel, post.post_id)
    for entity in post.entities or []:
        origin_text = ''.join(text[entity.offset:entity.offset + entity.length])
        to_replace = entity.url if hasattr(entity, 'url') else origin_text
        to_replace = getLinkReplace(to_replace)
        text[entity.offset] = to_replace
        if entity.offset + entity.length == len(text) and origin_text == 'source':
            text[entity.offset] = '\n\n' + to_replace
        for index in range(entity.offset + 1, entity.offset + entity.length):
            if text[index] != '\n':
                text[index] = ''
    text = ''.join(text)
    text = '\n'.join([line.strip() for line in text.split('\n')]).strip()
    return text

def addSuffix(status_text, post, album):
    if post.file:
        return status_text + '\n\n' + album.url
    if not status_text:
        return album.url
    return status_text

async def runImp():
    removeOldFiles('tmp', day=0.1)
    channels = list(credential['channels'].keys())
    random.shuffle(channels)
    for channel in channels:
        if tooClose(channel):
            continue
        for album, post in getPosts(channel):
            if existing.get(album.url):
                continue
            if credential['channels'][channel].get('raw_text'):
                status_text = await getRawText(channel, post)
            else:
                status_text = await getText(channel, post)
                status_text = addSuffix(status_text, post, album)
            if credential['channels'][channel].get('cut_text'):
                status_text = cutText(status_text, credential['channels'][channel].get('splitter'))
                if not lenOk(status_text) and credential['channels'][channel].get('second_splitter'):
                    status_text = cutText(status_text, credential['channels'][channel].get('second_splitter'))
            if len(status_text) > 500: 
                continue
            existing.update(album.url, -1) # place holder
            result = await post_twitter(channel, post, album, status_text)
            if not result:
                continue
            existing.update(album.url, result.id)
            return # only send one item for each run

async def run():
    await runImp()
    await telepost.exitTelethon()
        
if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())
    loop.close()