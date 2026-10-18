import requests
from bs4 import BeautifulSoup

def scrape_url(article_url):
    url = article_url
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    return soup

def scrape_article(article_url):
    article = scrape_url(article_url)

    sections = article.find_all('section')
    article_paragraphs = []
    article_text = ""

    for section in sections:
        paragraphs = section.find_all("p")
        for paragraph in paragraphs:
            article_paragraphs.append(paragraph.text)

    for p in article_paragraphs:
        article_text = article_text + "\n" + p

    return article_text




