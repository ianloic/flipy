'''Flipy - simple Flickr API wrapper'''

from urllib import urlencode, quote, urlopen
import lxml.etree as ET

'''
How Flickr responses map to Python objects in Flipy

<rsp>
  A successful response will be either the single wrapped child or a list of
  the wrapped children if there are multiple children. An unsuccessful response
  will map to an exception.

Attributes on nodes will map to attributes on objects.
Single child nodes will map to attributes on objects.
Multiple child nodes with the same tagName will mape to list attributes on 
objects.
Nodes without attributes or (node) children will map to strings.
For a node <foos> it will be a list-like object containing direct children 
<foo>
'''

class Wrapper(object):
  CUSTOM={}
  @classmethod
  def get(klass, flickr, node):
    # nodes without attributes or node children map to their text value
    if len(node.attrib) == 0 and len(node) == 0:
      return node.text
    # look for a custom wrapper constructor
    if klass.CUSTOM.has_key(node.tag):
      constructor = klass.CUSTOM[node.tag]
      return constructor(flickr, node)
    else:
      return klass(flickr, node)

  def __init__(self, flickr, node):
    self.__node = node
    self.flickr = flickr
    self.__children = []
    if node.tag.endswith('s'):
      self.__children = [Wrapper.get(flickr, c) 
          for c in node.findall('./%s' % node.tag[:-1])]

  def __getattr__(self, key):
    # if we have an attribute named @key, return its value
    if self.__node.attrib.has_key(key):
      return self.__node.get(key)
    # look for immediate children named @key
    elems = self.__node.findall('./%s' % key)
    if len(elems) == 1:
      return Wrapper.get(elems[0])
    else:
      return [Wrapper.get(e) for e in elems]

  def __str__(self):
    return ET.tostring(self.__node)

  def __getitem__(self, key):
    return self.__children[key]

  def __len__(self):
    return len(self.__children)


class wrapper_for(object):
  def __init__(self, tag):
    self.__tag = tag
  def __call__(self, f):
    Wrapper.CUSTOM[self.__tag] = f
    return f


@wrapper_for('rsp')
def rsp_wrapper(flickr, node):
  '''This wrapper just returns the (expected) single body or throws an 
  exception in the case of an error'''
  assert node.get('stat') == 'ok'
  children = node.getchildren()
  if len(children) == 1:
    return Wrapper.get(flickr, children[0])
  else:
    return [Wrapper.get(flickr, c) for c in children]


@wrapper_for('user')
class User(Wrapper):
  def photos(self, **args):
    args['user_id'] = self.nsid
    return self.flickr.page(self.flickr.photos.search, **args)


@wrapper_for('photo')
class Photo(Wrapper):
  def info(self):
    return flickr.photos.getInfo(photo_id = self.id, secret = self.secret)


class Method(object):
  def __init__(self, flickr, methodName):
    self.flickr = flickr
    self.methodName = methodName

  def __getattr__(self, key):
    return Method(self.flickr, self.methodName+'.'+key)

  def __call__(self, **args):
    return self.flickr(self.methodName, **args)


class Flipy(object):
  def __init__(self, api_key):
    self.default_args = {'api_key': api_key}

  def __getattr__(self, key):
    return Method(self, 'flickr.'+key)

  def __call__(self, method, **args):
    # collect and flatten arguments
    a = self.default_args.copy()
    a['method'] = method
    for k,v in args.items():
      if isinstance(v, list):
        a[k] = ','.join(v)
      else:
        a[k] = v
    url = 'http://flickr.com/services/rest?' + urlencode(a)
    return self.parse_response(self.get(url))

  def page(self, function, **args):
    args['page'] = 1
    while True:
      results = function(**args)
      for result in results:
        yield result
      if results.page == results.pages:
        break
      args['page'] = args['page'] + 1

  def get(self, url):
    '''Do an HTTP get for the supplied @url, return the response as a string'''
    return urlopen(url).read()

  def parse_response(self, string):
    '''Parse a response string into objects'''
    return Wrapper.get(self, ET.fromstring(string))


if __name__ == '__main__':
  flickr = Flipy('7e472304ad52ebcc5a266463cd247ad3')
  me = flickr.people.findByUsername(username='ianloic')
