import requests
from bs4 import BeautifulSoup, NavigableString
import json
from enum import Enum, IntEnum
from typing import Optional, Dict, List
from pydantic import BaseModel, Schema
from pprint import pprint
from fastapi import HTTPException
import dateutil.parser
from datetime import datetime

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

class PostDetails(GalleryListPost):
	file_url: str
	date_posted: datetime = Schema(..., description="Date at which submission was posted, offset by account timezone (which is GMT-5 with DST by default)")
	category: str
	theme: str
	species: Optional[str]
	gender: Optional[str]
	favorites: int
	comments: int
	views: int
	resolution: Optional[str]
	keywords: List[str]


def submission_file_type(category: str) -> str:
	# FA incorrectly categorizes podcasts as images
	# Probably because you can't actually upload podcasts as audio
	"""
	switch($category) {
        case '13':
        case '14':
        case '15' : return 'text';
        case '16' : return 'audio';
        default   : return 'image';
    }
	"""

	if (category == "Story" or category == "Poetry" or category == "Prose"): return 'text'
	if (category == "Music"): return 'audio'
	return 'image'

def scrape_submission(submission_id: int) -> PostDetails:
	resp = requests.get(f"https://www.furaffinity.net/full/{submission_id}")

	dom_input = BeautifulSoup(resp.content, features="html.parser")

	page_id = get_page_id(dom_input)

	if (page_id == 'matureimage-error'): raise HTTPException(status_code=403, detail='You are not allowed to view this image due to the content filter settings.')
	if (page_id == 'redirect'):  raise HTTPException(status_code=401, detail='The owner of this page has elected to make it available to registered users only.')
	if (page_id != 'submission'): raise WrongPageException(page_id)

	image_node = dom_input.find(id='submissionImg')
	action_bar = dom_input.find(class_='actions')

	details_table_node = image_node.find_next_sibling('table', class_='maintable')
	download_button_node = action_bar.find('a', string='Download')

	properties = {}

	properties['title'] = image_node['alt']

	# Flash files don't have a thumbnail, meta is more reliable
	# properties['preview_img'] = image_node['data-preview-src']
	properties['preview_img'] = dom_input.find('meta', dict(property='og:image:secure_url'))['content']
	properties['file_url'] = download_button_node['href']

	details_props = submission_details_node_to_props(details_table_node)
	properties.update(details_props)

	properties['rating'] = dom_input.find('meta', dict(name='twitter:data2'))['content']
	properties['permalink'] = dom_input.find('meta', dict(name='twitter:url'))['content']
	properties['id'] = submission_id
	
	properties['type'] = submission_file_type(properties['category'])

	return PostDetails(**properties)

def submission_details_node_to_props(details_table: BeautifulSoup):
	details_rows = details_table.find_all('tr', recursive=False)
	properties = {}


	title_cell = details_rows[0].td
	stats_cell = details_table.find(class_='stats-container')
	description_cell = details_rows[1].td

	#properties['title'] = title_cell.b.string
	properties['username'] = title_cell.a.string
	#properties['user_profile'] = title_cell.a['href']


	stat_keys = stats_cell.findAll('b')
	# Seek the next <br> and move back once to find the text/tags without getting bogged down by whitespace
	stat_ends = [tag.find_next('br') for tag in stat_keys]
	stat_next_text = [tag.previous_sibling for tag in stat_ends]

	stat_dict = {
		# Posting date is the only remaining tag at this point, and the real date is in its title attr
		key.text[:-1].lower() : val.strip() if type(val) is NavigableString else val['title']
		for (key, val) in zip(stat_keys, stat_next_text)
		if key is not val
	}

	stat_dict['date_posted'] = dateutil.parser.parse(stat_dict['posted'])
	del stat_dict['posted']

	properties.update(stat_dict)

	keywords_node = stats_cell.find(id='keywords')

	if (keywords_node is None):
		properties['keywords'] = []
	else:
		properties['keywords'] = [tag.text for tag in stats_cell.find(id='keywords').find_all('a')]

	description_avatar = description_cell.a
	#properties['user_avatar'] = description_avatar.img['src']
	properties['lower'] = description_avatar.img['alt']

	# I don't think that can be restored to bbcode anyway
	description_avatar.extract()
	properties['description'] = description_cell.text.strip()

	return properties

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
