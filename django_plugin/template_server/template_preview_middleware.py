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
import json

from functools import partial

from django.http import HttpResponse
from django.conf import settings
from django.contrib.staticfiles import views
from django.template import Template, Context

from template_parser.context import get_context


class OverAccomodatingContextItem(object):
    def __init__(self, context_dict, value, root=""):
        self._context_dict = context_dict
        self._root = root
        self._value = value
        self._iterator_count = 0

    def __str__(self):
        return self._value

    def __repr__(self):
        return self._value

    def __unicode__(self):
        return unicode(self._value)

    def __getattribute__(self, attr):
        g = partial(object.__getattribute__, self)

        if attr.startswith("_"):
            return g(attr)
        full_path = ".".join((g("_root"), attr))
        c_dict = g("_context_dict")
        if full_path in c_dict:
            c_value = c_dict[full_path]
            children = full_path + "."
            #Seems that if in a leaf, template needs a value
            if [i for i in c_dict if i.startswith(children)]:
                return OverAccomodatingContextItem(c_dict, c_value, full_path)
            else:
                return c_value
        else:
            raise AttributeError

    def __len__(self):
        val = self._value
        if val.isalnum():
            return len(val)
        return 1

    def __iter__(self):
        return self

    def __int__(self):
        return int(self._value)

    def __float__(self):
        return float(self._value)

    def next(self):
        if self._iterator_count > 0:
            self._iterator_count = 0
        else:
            self._iterator_count = 1
            iteritem = ".".join((self._root, "0"))
            c_dict = self._context_dict
#            for each_item in c_dict:
            if iteritem in c_dict:
#            if each_item.startswith(iteritem):
                c_value = c_dict[iteritem]
                return OverAccomodatingContextItem(c_dict, c_value, iteritem)
        raise StopIteration


class TemplatePreviewMiddleware(object):

    def process_request(self, request):
        if request.path.startswith(settings.STATIC_URL):
            static_path = request.path[len(settings.STATIC_URL):]
            return views.serve(request, static_path)
        else:
            if request.method == 'POST':
                template_str = request.POST.get('template',
                                                'no template provided')
                template = Template(template_str)
                if 'context' in request.POST:
                    context = json.loads(request.POST['context'])
                    magic_context = {}
                    for citem in context:
                        if "." not in context:
                            cvalue = context[citem]
                            magic_context[citem] = \
                            OverAccomodatingContextItem(context, cvalue, citem)
                    c = Context(magic_context)
                    return HttpResponse(template.render(c))
                else:
                    c = get_context(template)
                    return HttpResponse(json.dumps(c))
            else:
                return HttpResponse(
                """
                    <form action="." method="post">
                        Template: <input type="text" name="template"><br/>
                        Data: <textarea name="context"></textarea><br/>
                        <input type="submit">
                    </form>
                """)
