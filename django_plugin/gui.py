# -*- coding: utf-8 *-*
# This file is part of NINJA-DJANGO-PLUGIN
# (https://github.com/machinalis/ninja-django-plugin.)
#
# Copyright (C) 2012 Machinalis S.R.L <http://www.machinalis.com>
#
# Authors: Daniel Moisset <dmoisset at machinalis dot com>
#          Horacio Duran <hduran at machinalis dot com>
#
# NINJA-DJANGO-PLUGIN is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# any later version.
#
# NINJA-DJANGO-PLUGIN  is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with NINJA-DJANGO-PLUGIN; If not, see <http://www.gnu.org/licenses/>.
import logging
import subprocess
import re

from PyQt4.QtGui import QTreeWidget
import os
import json
import urllib2
import urllib
from PyQt4.QtGui import QTreeWidgetItem
from PyQt4.QtGui import QVBoxLayout
from PyQt4.QtGui import QHeaderView
from PyQt4.QtGui import QWidget
from PyQt4.QtGui import QAbstractItemView
from PyQt4.QtGui import QPushButton
from PyQt4.QtCore import SIGNAL

from ninja_ide.gui.explorer.explorer_container import ExplorerContainer
from ninja_ide.core import plugin
from ninja_ide.core.plugin_interfaces import IProjectTypeHandler
from ninja_ide.core.plugin_interfaces import implements
from ninja_ide.core.file_manager import belongs_to_folder

from template_parser.context import get_context

from copy import deepcopy
from collections import namedtuple

from django.template import Template
from django.conf import settings

IP_RE = re.compile("(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"\
                    "(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?):\d{1,5}")

logger = logging.getLogger('ninja-django-plugin.django_plugin.gui')
logging.basicConfig()
logger.setLevel(logging.DEBUG)
DEBUG = logger.debug

settings.configure(TEMPLATE_DIRS=tuple())
Node = namedtuple('Node', ['value', 'children'])
TEMPLATE_RE = re.compile("\{\{.+?\}\}")
PROJECT_TYPE = "Django App"


def make_data(url, *args, **kwargs):
    return url, urllib.urlencode(kwargs)


class DjangoContextItem(object):
    def __init__(self, item):
        self.__item = item

    def __len__():
        return 0


def parse_django_template(text):
    template = Template(text)
    return get_context(template)


class DjangoContext(object):
    """A Mock object that constructs a template like context with a list
    of the variables used in such template thus providing the required
    context for it to be rendered.
    """

    def __init__(self, context_text=""):
        self._model = dict()
        self._context_list = []
        self.update_context(context_text)
        self._process_context_list()

    def __iter__(self):
        for each_child in self._model:
            yield each_child

    def __getitem__(self, key):
        return self._model[key]

    def update_context(self, context_text):
        context_list = json.loads(context_text)
        current, new = set(self._context_list), set(context_list)
        new = new.difference(current)
        if new:
            self._context_list = self._context_list + list(new)
            self._process_context_list()

    def set_context(self, context_text):
        context_list = json.loads(context_text)
        self._context_list = context_list
        self._model = dict()
        self._process_context_list(context_list)

    def get_context(self):
        """Serialize current tree and return context in list form"""
        return self._serialize_context_list()

    context = property(get_context, set_context)

    def _process_context_list(self):
        """Take a list of paths and transform it into a tree structure"""
        self._context_list.sort()
        empty_node = dict(value=None, children=dict())
        for each_item in self._context_list:
            paths = each_item.split('.')
            branch = self._model
            for path in paths:
                node = branch.setdefault(path, deepcopy(empty_node))
                branch = node.get("children")

    def _serialize_context_list(self):
        """Tranform the current context tree and transform it into context"""
        context = []
        for each_item in self._model:
            if each_item not in context:
                each_item_value = self._model[each_item].get("value")
                each_item_value = each_item_value and \
                                unicode(each_item_value) or u""
                context.append((each_item, each_item_value))
            for each_tree_path, each_tree_value in \
                self._walk_tree(self._model[each_item]):
                path = [each_item, each_tree_path]
                path = [unicode(a) for a in path if a is not None]

                str_clear_path = ".".join(path)
                if (str_clear_path not in context) and \
                    (str_clear_path != each_item):
                    each_tree_value = each_tree_value and \
                                        unicode(each_tree_value) or u""
                    context.append((str_clear_path, each_tree_value))

        return dict(context)

    def _walk_tree(self, parent):
        """Recursively walk the tree to reconstruct the path"""
        children = parent.get("children")
        if children:
            for each_child in children:
                yield each_child, children.get(each_child).get("value")
                for each_path, each_value in \
                    self._walk_tree(children[each_child]):
                    path = [each_child] + [each_path]
                    path = [a for a in path if a is not None]
                    yield ".".join(path), each_value


class DjangoContextTreeItem(QTreeWidgetItem):
    def __init__(self, parent, name, node):
        QTreeWidgetItem.__init__(self, parent)
        self._parent = parent
        self.setText(0, name)
        self._node = node
        value = node.get("value") and node.get("value") or ""
        self.setText(1, value)
        self._recurse_children()

    def _recurse_children(self):
        children = self._node.setdefault("children", {})
        for each_child in children:
            DjangoContextTreeItem(self, each_child, children[each_child])

    def value_changed(self):
        self._node["value"] = self.text(1)


class DjangoContextExplorer(QTreeWidget):
    def __init__(self, context=None):
        QTreeWidget.__init__(self)
        self._editing = None
        self._context = context
        self.setSelectionMode(QTreeWidget.SingleSelection)
        self.setAnimated(True)
        self.header().setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.header().setResizeMode(0, QHeaderView.ResizeToContents)
        self.header().setStretchLastSection(False)
        self.setColumnCount(2)
        self.setHeaderLabels(("Label", "Value"))
        s_dclicked = "itemDoubleClicked(QTreeWidgetItem *, int)"
        self.connect(self, SIGNAL(s_dclicked), self.double_clicked_item)
        s_ichanged = "itemChanged(QTreeWidgetItem *, int)"
        self.connect(self, SIGNAL(s_ichanged), self.item_changed)
        s_iclicked = "itemClicked(QTreeWidgetItem *, int)"
        self.connect(self, SIGNAL(s_iclicked), self.item_clicked)

    def populate(self, context=None):
        if context:
            self._context = context
        self.clear()
        for each_item in self._context:
            DjangoContextTreeItem(self, each_item, self._context[each_item])

    def double_clicked_item(self, item, column):
        if column == 1:
            if self._editing:
                self.closePersistentEditor(*self._editing)
            self._editing = (item, column)
            self.openPersistentEditor(item, column)
        elif self._editing:
            self.closePersistentEditor(*self._editing)
            self._editing = None

    def item_changed(self, item, column):
        if self._editing:
            self.closePersistentEditor(item, column)
            item.value_changed()
            self._editing = None

    def item_clicked(self, item, column):
        if self._editing and (item != self._editing[0]):
            self.closePersistentEditor(*self._editing)
            self._editing = None

    def get_context(self):
        return self._context.get_context()


@implements(IProjectTypeHandler)
class DjangoProjectType(object):
    def __init__(self, locator):
        self.locator = locator

    def get_pages(self):
        """
        Returns a collection of QWizardPage
        """
        pass

    def on_wizard_finish(self, wizard):
        """
        Called when the user finish the wizard
        @wizard: QWizard instance
        """
        pass

    def get_context_menus(self):
        """"
        Returns a iterable of QMenu
        """
        return tuple()


class DjangoPluginMain(plugin.Plugin):
    def initialize(self, *args, **kwargs):
        ec = ExplorerContainer()
        super(DjangoPluginMain, self).initialize(*args, **kwargs)
        self._c_explorer = DjangoContextExplorer()
        self._contexts = dict()
        render = QPushButton('Render')
        refresh = QPushButton('Refresh Variables')

        class TransientWidget(QWidget):
            def __init__(self, widget_list):
                super(TransientWidget, self).__init__()
                vbox = QVBoxLayout(self)
                for each_widget in widget_list:
                    vbox.addWidget(each_widget)

        tw = TransientWidget((render, refresh, self._c_explorer))
        ec.addTab(tw, "Django Template")
        editor_service = self.locator.get_service("editor")
        self._es = editor_service
        editor_service.currentTabChanged.connect(self._current_tab_changed)
        editor_service.fileSaved.connect(self._a_file_saved)

        refresh.connect(refresh, SIGNAL("clicked( bool)"),
                        self._do_refresh_vars)

        render.connect(render, SIGNAL("clicked( bool)"),
                        self._do_render_template)

        self.explorer_s = self.locator.get_service('explorer')
        # Set a project handler for NINJA-IDE Plugin
        self.explorer_s.set_project_type_handler(PROJECT_TYPE,
                DjangoProjectType(self.locator))
        self._current_file_name = ""
        self._django_template_renderers = {}
        self._current_tab_changed(editor_service.get_editor_path())

    def _start_django(self, fileName):
        if not self._is_django_project(fileName):
            return
        project = self._get_project_key(fileName)
        python_interpreter = project.venv
        if not python_interpreter:
            return
        script_name = os.path.join(os.path.dirname(__file__),
                                    "template_server", "server.py")
        args = (python_interpreter, "-u", script_name, project.path, "settings")
        sp = subprocess.Popen(args, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        url = ""
        while not url:
            each_line = sp.stdout.readline()
            match = IP_RE.findall(each_line)
            if match:
                url = "http://%s" % match[0]
        return {"url": url, "process": sp}

    def _is_django_project(self, fileName):
        a_project = self._get_project_key(fileName)
        return a_project and (a_project.projectType == PROJECT_TYPE)

    def _get_project_key(self, fileName):
        fileName = unicode(fileName)
        projects_obj = self.explorer_s.get_opened_projects()
        for each_project in projects_obj:
            if belongs_to_folder(unicode(each_project.path), fileName):
                return each_project

    def _is_template(self, fileName):
        fileName = unicode(fileName)
        if self._is_django_project(fileName) and TEMPLATE_RE.findall(
                self.locator.get_service("editor").get_text()):
            return True

    def _do_refresh_vars(self, *args, **kwargs):
        self._load_context_for(self._es.get_editor_path())

    def _do_render_template(self, *args, **kwargs):
        path = self._es.get_editor_path()
        project_key = self._get_project_key(path).path
        if project_key not in self._django_template_renderers:
            self._current_tab_changed(path)
        url = self._django_template_renderers[project_key]["url"]
        current_text = self.locator.get_service("editor").get_text()
        context = json.dumps(self._c_explorer.get_context())
        values = {"template": current_text.encode("utf-8"),
                "context": context}
        request = urllib2.Request(*make_data(url, **values))

        DEBUG("Trying to render url %s" % url)
        misc_container_web = self.locator.get_service("misc")._misc._web
        try:
            page_content = urllib2.urlopen(request).read()
        except urllib2.URLError, err:
            page_content = err.read()
        misc_container_web.render_from_html(page_content, url)
        self.locator.get_service("misc")._misc._item_changed(2)

    def _load_context_for(self, context_key):
        project = self._get_project_key(context_key)
        project_key = project.path
        current_text = self.locator.get_service("editor").get_text()
        if project_key not in self._django_template_renderers:
            django_context = self._start_django(context_key)
            self._django_template_renderers[project_key] = django_context
            if not django_context:
                return
        if self._django_template_renderers[project_key] is None:
            return
        url = self._django_template_renderers[project_key]["url"]
        values = {"template": current_text.encode("utf-8")}
        req = urllib2.Request(*make_data(url, **values))
        context = urllib2.urlopen(req).read()

        if self._contexts.get(context_key, None):
            self._contexts[context_key].update_context(context)
        else:
            self._contexts[context_key] = DjangoContext(context)

    def _a_file_saved(self, fileName):
        fileName = unicode(fileName)
        if self._is_template(fileName):
            self._load_context_for(fileName)
            self._c_explorer.populate(self._contexts[fileName])

    def _current_tab_changed(self, fileName):
        self._current_file_name = unicode(fileName)
        if self._is_template(fileName):
            if not (self._current_file_name in self._contexts):
                self._load_context_for(self._current_file_name)
            self._c_explorer.populate(self._contexts[self._current_file_name])
        else:
            self._c_explorer.clear()

    def finish(self):
        super(DjangoPluginMain, self).finish()
        for each_sp in self._django_template_renderers:
            self._django_template_renderers[each_sp]["process"].kill()
            stdout = self._django_template_renderers[each_sp]["process"].stdout
            for line in iter(stdout.readline, ''):
                print line.rstrip()
            self._django_template_renderers[each_sp]["process"].wait()

    def get_preferences_widget(self):
        return super(DjangoPluginMain, self).get_preferences_widget()

    def get_pages(self):
        """
        Should Returns a collection of QWizardPage or subclass
        """
        return super(DjangoPluginMain).get_pages()

    def on_wizard_finish(self, wizard):
        """
        Called when the user finish the wizard
        """
        super(DjangoPluginMain).on_wizard_finish()

    def get_context_menus(self):
        """"
        Should Returns an iterable of QMenu for the context type of the new
        project type
        """
        return super(DjangoPluginMain).get_context_menus()
