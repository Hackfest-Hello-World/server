import requests
import time

HEADERS = {
    "x-rapidapi-host": "twitter241.p.rapidapi.com",
    "x-rapidapi-key": "cc17d03003msh9b10bdb1326faddp109cb2jsnfdab0ff25424"
}

def fetch_user_details(username):
    url = f"https://twitter241.p.rapidapi.com/user?username={username}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch user details: {response.status_code} - {response.text}")

    data = response.json()
    data1 = data['result']["data"]["user"]['result']['rest_id']

    # Extract the useful parts (you can expand this as needed)
    # user_data = {
    #     "username": data.get("username"),
    #     "full_name": data.get("full_name"),
    #     "id": data.get("id"),
    #     "bio": data.get("biography"),
    #     "followers": data.get("edge_followed_by", {}).get("count"),
    #     "following": data.get("edge_follow", {}).get("count"),
    #     "profile_pic_url": data.get("profile_pic_url_hd") or data.get("profile_pic_url"),
    #     "is_verified": data.get("is_verified"),
    #     "is_private": data.get("is_private"),
    # }

    return data1

def fetch_user_posts(username,count=1):
    url = f"https://twitter241.p.rapidapi.com/user-tweets?user={username}&count={count}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch user posts: {response.status_code} - {response.text}")

    data = response.json()
    item1 = data['result']['timeline']['instructions'][1]['entry']['content']['itemContent']['tweet_results']['result']['legacy']['id_str']
    items=data['result']['timeline']['instructions'][2]['entries']

    posts = [item1]

    for item in items:
        
        try:
            post_id = item['content']['itemContent']['tweet_results']['result']['legacy']['id_str']

        # caption = item.get("caption")
        # caption_text = caption.get("text") if caption else ""

        # # Tags
        # tagged_users = []
        # usertags = item.get("usertags", {}).get("in", [])
        # for tag in usertags:
        #     user_info = tag.get("user", {})
        #     tagged_users.append(user_info.get("username"))

        # post_info = {
        #     "post_id": post_id,
        #     "caption": caption_text,
        #     "tagged_users": tagged_users,
        #     "timestamp": item.get("taken_at")
        # }

            posts.append(post_id)
        except:
            continue

    return posts

def fetch_post_comments(post_pk):
    print(post_pk)
    url = f"https://twitter241.p.rapidapi.com/comments?pid={post_pk}&count=5&rankingMode=Relevance"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        try:
            items=data['result']['instructions'][0]['entries']
            comments=[]
            for x in items:
                # print("hi")
                try:
                    comment=x['content']['itemContent']['tweet_results']['result']['legacy']['full_text']
                    comments.append(comment)
                except:
                    continue
            return {'id':post_pk,'comments':comments}
        except:
            return {'id':post_pk,'comments':[]}

        # Create a structured result object
        # result = {
        #     "post_id": post_pk,
        #     "caption": {
        #         "text": None,
        #         "username": None,
        #         "created_at": None
        #     },
        #     "comments": []
        # }

        # # Fill caption data if available
        # caption = data.get("caption")
        # if caption:
        #     result["caption"] = {
        #         "text": caption.get("text"),
        #         "username": caption.get("user", {}).get("username"),
        #         "created_at": caption.get("created_at_utc")
        #     }

        # # Fill comments data
        # for c in data.get("comments", []):
        #     result["comments"].append({
        #         "text": c.get("text"),
        #         "username": c.get("user", {}).get("username"),
        #         "likes": c.get("comment_like_count", 0),
        #         "created_at": c.get("created_at_utc")
        #     })

        # return result

    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {e}")
    except Exception as e:
        raise Exception(f"Error processing comment data: {e}")
    

def fetch_comments(username):
    id=fetch_user_details(username)
    posts=fetch_user_posts(id)
    comments=[]
    for post in posts:
        comments.append(fetch_post_comments(post))
        time.sleep(0.5)
    return comments
