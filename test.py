import tweepy
import yaml
import plain_db

existing = plain_db.loadLargeDB('existing', isIntValue=True)

with open('credential') as f:
    credential = yaml.load(f, Loader=yaml.FullLoader)

def addAccount():
    auth = tweepy.OAuthHandler(credential['twitter_consumer_key'], credential['twitter_consumer_secret'])
    auth.get_authorization_url()
    verifier = ''
    auth.get_access_token(verifier)

def manualAddExisting():
    for post_id in range(93000, 93885):
        existing.update('https://t.me/weibo_one/%d' % post_id, -1) # place holder


if __name__ == '__main__':
    ...
    # addAccount()
    # manualAddExisting()

