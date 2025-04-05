import requests

HEADERS = {
    "x-rapidapi-host": "instagram230.p.rapidapi.com",
    "x-rapidapi-key": "3a8e74bc89mshe81a75341832f10p1e16bajsnd764201e73a0"
}

def fetch_user_details(username):
    url = f"https://instagram230.p.rapidapi.com/user/details?username={username}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch user details: {response.status_code} - {response.text}")

    data = response.json()
    data = data["data"]["user"]

    # Extract the useful parts (you can expand this as needed)
    user_data = {
        "username": data.get("username"),
        "full_name": data.get("full_name"),
        "id": data.get("id"),
        "bio": data.get("biography"),
        "followers": data.get("edge_followed_by", {}).get("count"),
        "following": data.get("edge_follow", {}).get("count"),
        "profile_pic_url": data.get("profile_pic_url_hd") or data.get("profile_pic_url"),
        "is_verified": data.get("is_verified"),
        "is_private": data.get("is_private"),
    }

    return user_data

def fetch_user_posts(username):
    url = f"https://instagram230.p.rapidapi.com/user/posts?username={username}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch user posts: {response.status_code} - {response.text}")

    data = response.json()
    items = data.get("items")

    posts = []

    for item in items:
        post_id = item.get("pk")

        caption = item.get("caption")
        caption_text = caption.get("text") if caption else ""

        # Tags
        tagged_users = []
        usertags = item.get("usertags", {}).get("in", [])
        for tag in usertags:
            user_info = tag.get("user", {})
            tagged_users.append(user_info.get("username"))

        post_info = {
            "post_id": post_id,
            "code":item.get('code'),
            'view':item.get('play_count'),
            'timestamp':item.get('device_timestamp'),
            "caption": caption_text,
            "tagged_users": tagged_users,
            "timestamp": item.get("taken_at")
        }

        posts.append(post_info)

    return posts

def fetch_post_comments(post_pk):
    url = f"https://instagram230.p.rapidapi.com/post/comments?pk={post_pk}"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()

        # Create a structured result object
        result = {
            "post_id": post_pk,
            "caption": {
                "text": None,
                "username": None,
                "created_at": None
            },
            "comments": []
        }

        # Fill caption data if available
        caption = data.get("caption")
        if caption:
            result["caption"] = {
                "text": caption.get("text"),
                "username": caption.get("user", {}).get("username"),
                "created_at": caption.get("created_at_utc")
            }

        # Fill comments data
        for c in data.get("comments", []):
            result["comments"].append({
                "text": c.get("text"),
                "username": c.get("user", {}).get("username"),
                "likes": c.get("comment_like_count", 0),
                "created_at": c.get("created_at_utc")
            })

        return result

    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {e}")
    except Exception as e:
        raise Exception(f"Error processing comment data: {e}")
    

def build_user_schema(username):
    user_info = fetch_user_details(username)
    posts = fetch_user_posts(username)
    post_list = []
    for post in posts:
        caption = post.get("caption")
        caption_text = caption.get("text") if isinstance(caption, dict) else caption

        post_data = {
            "post_id": post.get("pk"),
            "caption": caption_text,
            "media_type": post.get("media_type"),
            "taken_at": post.get("taken_at"),
            "like_count": post.get("like_count"),
            "comment_count": post.get("comment_count"),
            "image_versions": post.get("image_versions2", {}).get("candidates") if post.get("image_versions2") else None,
            "video_versions": post.get("video_versions") if post.get("video_versions") else None,
            "comments": post.get("comments", [])
        }
        post_list.append(post_data)

    return {
        "username": username,
        "profile": user_info,
        "posts": post_list
    }