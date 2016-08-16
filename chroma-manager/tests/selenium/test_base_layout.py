""" Test Base Layout """

from tests.selenium.base import SeleniumBaseTestCase
from tests.selenium.utils.element import wait_for_element_by_css_selector
from tests.selenium.views.base_layout import Baselayout


class TestBaseLayout(SeleniumBaseTestCase):
    base_page_layout = None
    pages = None

    def setUp(self):
        super(TestBaseLayout, self).setUp()
        self.base_page_layout = Baselayout(self.driver)
        self.pages = self.base_page_layout.navigation_pages

    def test_all_pages(self):
        for page in self.pages:
            self.check_base_page_layout(page)

    def check_base_page_layout(self, page):
        self.navigation.go(page)
        for menu_selector in self.base_page_layout.menu_element_ids:
            self.assertTrue(wait_for_element_by_css_selector(self.driver, menu_selector, 10), 'Menu with element id:' + menu_selector + ' is missing on page: ' + page)

        for image_selector in self.base_page_layout.image_element_css:
            self.assertTrue(wait_for_element_by_css_selector(self.driver, image_selector, 10), 'Image with element id:' + image_selector + ' is missing on page: ' + page)