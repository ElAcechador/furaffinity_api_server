from fastapi import FastAPI
from typing import List
from .test import scrape_artist_gallery, scrape_search_posts, scrape_submission, PageSize, scrape_browse_posts, GalleryListPost, BrowsePostsConfiguration, SearchPostsConfiguration, PostDetails

app = FastAPI()

@app.post("/search/", response_model=List[GalleryListPost])
async def search_posts(config: SearchPostsConfiguration):
	return scrape_search_posts(config)

@app.post("/browse/", response_model=List[GalleryListPost])
async def browse_posts(config: BrowsePostsConfiguration):
	return scrape_browse_posts(config)

@app.get("/gallery/{artist_name}/", response_model=List[GalleryListPost])
async def artist_gallery(artist_name: str, page_num: int = 1, perpage: PageSize = PageSize.medium):
	return scrape_artist_gallery(artist_name, page_num, perpage)

@app.get("/submission/{submission_id}/", response_model=PostDetails)
async def submission(submission_id: int):
	return scrape_submission(submission_id)
