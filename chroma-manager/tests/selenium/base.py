import datetime
import logging
import os
import sys
import time


from django.utils.unittest import TestCase
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support.wait import WebDriverWait
from testconfig import config

from tests.selenium.utils.constants import wait_time
from tests.selenium.utils.patch_driver_execute import patch_driver_execute


LOG_NAME_TEMPLATE = "selenium_oldui_%s_%s.log" % (config['browser'], '%s')
loggers = {}


class LogType(object):
    # The test log captures logging from our own test code
    TEST = 'test'

    # The browser log captures the browser console
    BROWSER = 'browser'

    # The driver log captures logging from the browser drivers (ex, Chromedriver, FirefoxDriver)
    DRIVER = 'driver'

    ALL = [TEST, BROWSER, DRIVER]


def configure_selenium_log(log_name, use_timestamp=True):
    log = logging.getLogger(log_name)
    log.setLevel(logging.DEBUG)
    handler = logging.FileHandler(LOG_NAME_TEMPLATE % log_name)
    handler.setLevel(logging.DEBUG)
    if use_timestamp:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
    log.addHandler(handler)
    loggers[log_name] = log


configure_selenium_log(LogType.TEST, use_timestamp = True)
configure_selenium_log(LogType.BROWSER, use_timestamp = False)
configure_selenium_log(LogType.DRIVER, use_timestamp = False)


def quiesce_api(driver, timeout):
    for i in xrange(timeout):
        busy = driver.execute_script('return ($.active != 0);')
        if not busy:
            return
        else:
            time.sleep(1)
    raise RuntimeError('Timeout')


def wait_for_transition(driver, timeout):
    """Wait for a job to complete.  NB the busy icon must be visible initially
    (call quiesce after state change operations to ensure that if the busy icon
    is going to appear, it will have appeared)"""

    WebDriverWait(driver, timeout).until(
        lambda driver: driver.find_element_by_id("notification_icon_jobs").value_of_css_property('display') == 'none',
        'Timeout after %s seconds waiting for transition to complete' % timeout)

    # We have to quiesce here because the icon is hidden on command completion
    # but updates to changed objects are run asynchronously.
    quiesce_api(driver, timeout)


def take_debug_screenshot(driver, name):
    """Take a screenshot to use for debugging."""
    debug_screen_shot_dir = os.path.join(os.getcwd(), 'debug-screen-shots')

    if not os.path.exists(debug_screen_shot_dir):
        os.makedirs(debug_screen_shot_dir)

    filename = os.path.join(
        debug_screen_shot_dir,
        "%s_%s.png" % (
            name,
            datetime.datetime.now().isoformat()
        )
    )

    loggers[LogType.TEST].info("Saving screen shot to %s", filename)
    driver.get_screenshot_as_file(filename)


class SeleniumBaseTestCase(TestCase):
    """This is the base class for the test classes.
    The setUp() method is called during the
    initialization process. The tearDown() method is called
    irrespective of the status of the application.
    """
    def __init__(self, *args, **kwargs):
        super(SeleniumBaseTestCase, self).__init__(*args, **kwargs)
        self.log = loggers[LogType.TEST]

        self.driver = None
        self.standard_wait = wait_time['standard']
        self.medium_wait = wait_time['medium']
        self.long_wait = wait_time['long']

        self.browser = config['browser']

    def id(self):
        """We want to override the default description of each test to help differentiate
        the results when running multiple times with different browsers."""
        return "selenium_old_ui.%s.%s" % (self.browser, super(SeleniumBaseTestCase, self).id())

    def shortDescription(self):
        """Disable displaying the docstring instead of the test name in the test output"""
        return None

    def setUp(self):
        self.log_delimiter = "\nStarting test %s" % self.id()
        for log_name in LogType.ALL:
            loggers[log_name].info(self.log_delimiter)

        if not config['chroma_managers'][0]['server_http_url']:
            raise RuntimeError("Please set server_http_url in config file")

        if not self.driver:
            patch_driver_execute()

            if self.browser == 'Chrome':
                # Make sure we capture the chromedriver log for each test
                self.addCleanup(self._capture_chromedriver_log)

                # Set parameters to be passed to Chrome itself
                options = webdriver.ChromeOptions()
                options.add_argument('no-proxy-server')

                options.add_argument('enable-crash-reporter')
                options.add_argument('full-memory-crash-report')
                options.add_argument('enable-logging=stderr')
                options.add_argument('log-level=""')  # log-level interferes with v=1
                options.add_argument('v=1000')  # Get all levels of vlogs

                # Set parameters to be passed to ChromeDriver
                chromedriver_service_args = [
                    "--verbose",
                    "--log-path=%s" % os.path.join(os.path.sep, 'tmp', 'chromedriver.log')
                ]

                running_time = 0
                while running_time < self.long_wait and not self.driver:
                    try:
                        self.driver = webdriver.Chrome(
                            chrome_options=options,
                            service_args=chromedriver_service_args
                        )
                    except WebDriverException, e:
                        # Workaround for TEI-847: ChromeDriver has a bug where
                        # sometimes its port gets stolen out from under it, and
                        # there is no real way to prevent this from happening until
                        # they fix it. So we simply loop until we get a driver.
                        # Once this bug is resolved, we can convert this whole loop
                        # back to the single webdriver.Chrome() call.
                        self.log.error("Webdriver failed to start with the following exception: %s" % e)
                        if running_time >= self.long_wait:
                            raise
                    time.sleep(1)
                    running_time += 1

            elif self.browser == 'Firefox':
                # Enable the FirefoxDriver log
                driver_log_path = os.path.join(os.getcwd(), LOG_NAME_TEMPLATE % LogType.DRIVER)
                profile = webdriver.FirefoxProfile()
                profile.set_preference('webdriver.log.file', driver_log_path)
                profile.set_preference('security.use_mozillapkix_verification', False)
                self.driver = webdriver.Firefox(profile)

        self.addCleanup(self.stop_driver)
        self.addCleanup(self._capture_browser_log)
        self.addCleanup(self._take_screenshot_on_failure)
        self.addCleanup(self._capture_exception_modal_message)

        self.driver.set_window_size(1024, 768)
        self.driver.set_script_timeout(90)

        self.driver.get(config['chroma_managers'][0]['server_http_url'])

        from tests.selenium.utils.navigation import Navigation
        self.navigation = Navigation(self.driver, False)

        superuser_present = False
        for user in config['chroma_managers'][0]['users']:
            if user['is_superuser']:
                self.navigation.login(user['username'], user['password'])
                superuser_present = True
        if not superuser_present:
            raise RuntimeError("No superuser in config file")

        self.clear_all()

    def stop_driver(self):
        # It can be handy not to clean up after a failed test when a developer
        # is actively working on a test or troubleshooting a test failure and
        # to leave the browser window open. To provide for this, there is an
        # option in the config, clean_up_on_failure, that controls clean up on
        # failed tests. Cleanup will always occur for successful tests.
        # Beware that the un-cleaned-up tests will leave resources and processes
        # on your system that will not automatically be cleaned up.
        test_failed = False if sys.exc_info() == (None, None, None) else True
        if config.get("clean_up_on_failure"):
            self.log.info("Quitting driver after %s" % "failure" if test_failed else "success")
            self.driver.quit()
        elif not test_failed:
            self.log.info("Closing driver after success")
            self.driver.close()

    def clear_all(self):
        from tests.selenium.views.filesystem import Filesystem
        from tests.selenium.views.mgt import Mgt
        from tests.selenium.views.servers import Servers
        from tests.selenium.views.users import Users

        self.log.info("Clearing all objects")
        self.navigation.go('Configure', 'Filesystems')
        Filesystem(self.driver).remove_all()
        self.navigation.go('Configure', 'MGTs')
        Mgt(self.driver).remove_all()
        self.navigation.go('Configure', 'Servers')
        Servers(self.driver).remove_all()

        superuser_username = None
        for user in config['chroma_managers'][0]['users']:
            if user['is_superuser']:
                superuser_username = user['username']
        if not superuser_username:
            raise RuntimeError("Test config does not define a superuser")
        else:
            self.navigation.go('Configure', 'Users')
            Users(self.driver).delete_all_except(superuser_username)

    def volume_and_server(self, index, lustre_server = None):
        if not lustre_server:
            lustre_server = config['lustre_servers'][0]['nodename']

        server_config = None
        for server in config['lustre_servers']:
            if server['nodename'] == lustre_server:
                server_config = server
        if not server_config:
            raise RuntimeError("No lustre server found called '%s'" % lustre_server)

        volume = server_config['device_paths'][index]
        volume_label = config['device_path_to_label_map'][volume]

        return volume_label, server_config['nodename']

    def create_filesystem_with_server_and_mgt(self, host_list,
                                              mgt_host_name, mgt_device_node,
                                              filesystem_name,
                                              mdt_host_name, mdt_device_node,
                                              ost_host_name, ost_device_node, conf_params):
        from tests.selenium.views.volumes import Volumes
        from tests.selenium.views.mgt import Mgt
        from tests.selenium.views.servers import Servers
        from tests.selenium.views.create_filesystem import CreateFilesystem
        from tests.selenium.views.conf_param_dialog import ConfParamDialog

        self.log.info("Creating filesystem: %s MGT:%s/%s, MDT %s/%s, OST %s/%s" % (
            filesystem_name,
            mgt_host_name, mgt_device_node,
            mdt_host_name, mdt_device_node,
            ost_host_name, ost_device_node))

        self.navigation.go('Configure', 'Servers')
        self.server_page = Servers(self.driver)
        self.server_page.add_servers(host_list)

        self.navigation.go('Configure', 'Volumes')
        volume_page = Volumes(self.driver)
        for primary_server, volume_name in [(mgt_host_name, mgt_device_node), (mdt_host_name, mdt_device_node), (ost_host_name, ost_device_node)]:
            volume_page.set_primary_server(volume_name, primary_server)

        self.navigation.go('Configure', 'MGTs')
        self.mgt_page = Mgt(self.driver)
        self.mgt_page.create_mgt(mgt_host_name, mgt_device_node)

        self.navigation.go('Configure', 'Filesystems', 'Create_new_filesystem')
        create_filesystem_page = CreateFilesystem(self.driver)
        create_filesystem_page.enter_name(filesystem_name)
        create_filesystem_page.open_conf_params()
        ConfParamDialog(self.driver).enter_conf_params(conf_params)
        create_filesystem_page.close_conf_params()
        create_filesystem_page.select_mgt(mgt_host_name)
        create_filesystem_page.select_mdt_volume(mdt_host_name, mdt_device_node)
        create_filesystem_page.select_ost_volume(ost_host_name, ost_device_node)
        create_filesystem_page.create_filesystem_button.click()
        create_filesystem_page.quiesce()
        wait_for_transition(self.driver, self.long_wait)

    def create_filesystem_simple(self, host_list, filesystem_name, conf_params = None):
        """Pick some arbitrary hosts and volumes to create a filesystem"""
        if conf_params is None:
            conf_params = {}

        self.mgt_volume_name, self.mgt_server_address = self.volume_and_server(0)
        self.mdt_volume_name, self.mdt_server_address = self.volume_and_server(1)
        self.ost_volume_name, self.ost_server_address = self.volume_and_server(2)

        self.create_filesystem_with_server_and_mgt(
            host_list,
            self.mgt_server_address, self.mgt_volume_name,
            filesystem_name,
            self.mdt_server_address, self.mdt_volume_name,
            self.ost_server_address, self.ost_volume_name,
            conf_params)

    def _take_screenshot_on_failure(self):
        test_failed = False if sys.exc_info() == (None, None, None) else True

        if config['screenshots'] and test_failed:
            failed_screen_shot_dir = os.path.join(os.getcwd(), 'failed-screen-shots')

            if not os.path.exists(failed_screen_shot_dir):
                os.makedirs(failed_screen_shot_dir)

            filename = os.path.join(
                failed_screen_shot_dir,
                "%s_%s.png" % (
                    self.id(),
                    datetime.datetime.now().isoformat()
                )
            )

            self.log.info("Saving screen shot to %s", filename)
            self.driver.get_screenshot_as_file(filename)

    def _capture_exception_modal_message(self):
        from tests.selenium.views.modal import ExceptionModal
        exception_modal = ExceptionModal(self.driver)

        if exception_modal.is_open():
            self.log.error("Exception: %s", exception_modal.exception_message)
            self.log.error("Client Stack Trace: %s", exception_modal.stack_trace)

    def _capture_chromedriver_log(self):
        chromedriver_log = open(os.path.join(os.path.sep, 'tmp', 'chromedriver.log'), 'r')
        logs = [line.decode('string-escape')[:-1] for line in chromedriver_log.readlines()]
        self._capture_logs(LogType.DRIVER, logs)

    def _capture_browser_log(self):
        logs = self.driver.get_log(LogType.BROWSER)
        self._capture_logs(LogType.BROWSER, logs)

    def _capture_logs(self, log_name, logs):
        logger = loggers[log_name]

        if not isinstance(logs, (list, dict)):
            logs = []

        for log in logs:
            logger.info(log)