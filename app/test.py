import requests
from bs4 import BeautifulSoup
import json
from enum import Enum, IntEnum
from typing import Optional, Dict, List
from pydantic import BaseModel
from pprint import pprint
from fastapi import HTTPException

#pageid-matureimage-error/pageid-submission
#no way to tell if mature or adult images are enabled for account or to force it when sending queries

class WrongPageException(HTTPException):
	def __init__(self, bad_page_id):
		error_msg = f"Incorrect page ID recieved: '{bad_page_id}'"
		super().__init__(status_code=502, detail=error_msg)

class PageSize(IntEnum):
	small = 24
	medium = 48
	large = 72

class SearchQueryMode(Enum):
	any = 'any'
	all = 'all'
	extended = 'extended'

class SearchOrdering(Enum):
	relevancy = 'relevancy'
	date = 'date'
	popularity = 'popularity'

class SearchOrderDirection(Enum):
	asc = 'asc'
	desc = 'desc'

class SearchRange(Enum):
	day = 'day'
	three_days = '3days'
	week = 'week'
	month = 'month'
	all = 'all'

class SearchPostsConfiguration(BaseModel):
	mode: SearchQueryMode = SearchQueryMode.extended
	q: str # Extended mode search syntax follows sphynx search, see help on search page

	page: int = 1
	perpage: PageSize = PageSize.medium
	order_by: SearchOrdering = SearchOrdering.date
	order_direction: SearchOrderDirection = SearchOrderDirection.desc

	range: SearchRange = SearchRange.all
	rating_general: bool = True
	rating_mature: bool = False
	rating_adult: bool = False

	type_art: bool = True
	type_flash: bool = True
	type_photo: bool = True
	type_music: bool = True
	type_story: bool = True
	type_poetry: bool = True

class BrowsePostsConfiguration(BaseModel):
	cat:int = 1
	atype:int = 1
	species:int = 2006
	gender:int = 0
	perpage: PageSize = PageSize.medium

	rating_general: bool = True
	rating_mature: bool = False
	rating_adult: bool = False

class GalleryListPost(BaseModel):
	id: int
	title: str
	description: str
	username: str
	lower: str
	rating: str
	type: str
	preview_img: str
	permalink: str

def scrape_artist_gallery(artist_name: str, page_num: int = 1, perpage: PageSize = PageSize.medium) -> List[GalleryListPost]:
	resp = requests.get(f"https://www.furaffinity.net/gallery/{artist_name}/{page_num}", params=dict( perpage = perpage.value ))

	dom_input = BeautifulSoup(resp.content, features="html.parser")

	page_id = get_page_id(dom_input)
	if (page_id != 'galery'): raise WrongPageException(page_id)

	browse_section = dom_input.find(id="page-galleryscraps")
	descriptions: Optional[Dict[str, dict]]

	description_script = browse_section.find_next_sibling('script')

	if (description_script):
		description_json = description_script.string.split('    //\n')[0].partition('=')[2].strip('\n ;')
		descriptions = json.loads(description_json)

	gallery_section = browse_section.find('section', class_='gallery')

	return extract_gallery_data(gallery_section, descriptions)

def scrape_browse_posts(config: BrowsePostsConfiguration) -> List[GalleryListPost]:
	resp = requests.post("https://www.furaffinity.net/browse/", data=dict(
		cat = config.cat,
		atype = config.atype,
		species = config.species,
		gender = config.gender,
		perpage = config.perpage.value,

		rating_general = 1 if config.rating_general else None,
		rating_mature = 1 if config.rating_mature else None,
		rating_adult = 1 if config.rating_adult else None,

		go= "Update"
	))

	dom_input = BeautifulSoup(resp.content, features="html.parser")

	page_id = get_page_id(dom_input)
	if (page_id != 'browse'): raise WrongPageException(page_id)

	browse_section = dom_input.find(id="browse")
	descriptions: Optional[Dict[str, dict]]

	description_script = browse_section.find_next_sibling('script')

	if (description_script):
		description_json = description_script.string.partition('=')[2].strip('\n ;')
		descriptions = json.loads(description_json)

	gallery_section = browse_section.find('section', class_='gallery')

	return extract_gallery_data(gallery_section, descriptions)

def scrape_search_posts(config: SearchPostsConfiguration) -> List[GalleryListPost]:
	resp = requests.post("https://www.furaffinity.net/search/", data = {
		'mode': config.mode.value,
		'q': config.q,

		'page': config.page,
		'perpage': config.perpage.value,
		'order-by': config.order_by.value,
		'order-direction': config.order_direction.value,

		'range': 'all',
		'rating-general': 'on' if config.rating_general else None,
		'rating-mature': 'on' if config.rating_mature else None,
		'rating-adult': 'on' if config.rating_adult else None,

		'type-art': 'on' if config.type_art else None,
		'type-flash': 'on' if config.type_flash else None,
		'type-photo': 'on' if config.type_photo else None,
		'type-music': 'on' if config.type_music else None,
		'type-story': 'on' if config.type_story else None,
		'type-poetry': 'on' if config.type_poetry else None,

		'do_search': 'Search'
	})

	dom_input = BeautifulSoup(resp.content, features="html.parser")

	page_id = get_page_id(dom_input)
	if (page_id != 'search'): raise WrongPageException(page_id)

	gallery_section = dom_input.find('section', class_='gallery')
	descriptions: Optional[Dict[str, dict]] = None
	
	description_script = gallery_section.find_next_siblings('script')[-1]

	if (description_script):
		description_json = description_script.string.partition('=')[2].strip('\n ;')
		descriptions = json.loads(description_json)

	return extract_gallery_data(gallery_section, descriptions)

def extract_gallery_data(gallery_section: BeautifulSoup, post_descriptions: Optional[Dict[str, dict]]) -> List[GalleryListPost]:
	dom_posts = gallery_section.find_all('figure')

	return [gallery_dom_node_to_props(dom_post, post_descriptions) for dom_post in dom_posts]

def gallery_dom_node_to_props(dom_post: BeautifulSoup, post_descriptions: Optional[Dict[str, dict]]) -> GalleryListPost:
	properties = {}

	data_id = dom_post['id']
	if data_id.startswith('sid-'):
		post_id = data_id[4:]
		properties['id'] = int(post_id)

		if post_descriptions is not None:
			properties.update(post_descriptions[post_id])

	for data_class in dom_post['class']:
		if data_class.startswith('r-'):
			properties['rating'] = data_class[2:]
		elif data_class.startswith('t-'):
			properties['type'] = data_class[2:]
		elif data_class.startswith('u-'):
			properties['user'] = data_class[2:]
	
	preview_node = dom_post.find('img')
	properties['preview_img'] = preview_node['src']
	properties['permalink'] = preview_node.parent['href']

	return GalleryListPost(**properties)

def get_page_id(full_html: BeautifulSoup) -> Optional[str]:
	body_tag = full_html.body

	if body_tag is None:
		return None
	
	body_tag_id = body_tag['id']

	if body_tag_id is None:
		return None
	
	if body_tag_id.startswith('pageid-'):
		return body_tag_id[7:]
	
	return None
