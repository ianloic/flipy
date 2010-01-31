'''Flipy - simple Flickr API wrapper
Copyright 2010 Ian McKellar <http://ian.mckellar.org/>
Flipy is Free Software under the terms of the GNU LGPL. See lgpl.txt.
'''

from urllib import urlencode, quote, urlopen
import lxml.etree as ET
import hashlib

class Wrapper(object):
  CUSTOM={}
  @classmethod
  def custom(klass, tag):
    '''a decorator for defining custom wrappers'''
    def call(f): klass.CUSTOM[tag] = f
    return call

  @classmethod
  def get(klass, flickr, node):
    '''get a wrapper for the supplied node'''
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
    '''create a wrapper'''
    self.__node = node
    self.flickr = flickr
    self.__children = []
    if node.tag.endswith('s'):
      self.__children = [Wrapper.get(flickr, c) 
          for c in node.findall('./%s' % node.tag[:-1])]

  def __getattr__(self, key):
    '''get a wrapper attribute'''
    # if we have an attribute named @key, return its value
    if self.__node.attrib.has_key(key):
      return self.__node.get(key)
    # look for immediate children named @key
    elems = self.__node.findall('./%s' % key)
    if len(elems) == 1:
      return Wrapper.get(self.flickr, elems[0])
    elif len(elems) > 1:
      return [Wrapper.get(self.flickr, e) for e in elems]

  def __str__(self):
    return ET.tostring(self.__node)

  def __getitem__(self, key):
    '''get a wrapper item'''
    return self.__children[key]

  def __len__(self):
    '''how many items does this wrapper have'''
    return len(self.__children)




@Wrapper.custom('rsp')
def rsp_wrapper(flickr, node):
  '''This wrapper just returns the (expected) single body or throws an 
  exception in the case of an error'''
  assert node.get('stat') == 'ok'
  children = node.getchildren()
  if len(children) == 1:
    return Wrapper.get(flickr, children[0])
  else:
    return [Wrapper.get(flickr, c) for c in children]


@Wrapper.custom('user')
class User(Wrapper):
  '''wrap the <user> response with useful methods'''
  def photos(self, **args):
    args['user_id'] = self.nsid
    return self.flickr.page(self.flickr.photos.search, **args)


@Wrapper.custom('photo')
class Photo(Wrapper):
  '''wrap the <photo> response with useful methods'''
  def info(self):
    return flickr.photos.getInfo(photo_id = self.id, secret = self.secret)


class Method(object):
  '''method wrapper'''
  def __init__(self, flickr, methodName):
    self.flickr = flickr
    self.methodName = methodName

  def __getattr__(self, key):
    return Method(self.flickr, self.methodName+'.'+key)

  def __call__(self, **args):
    return self.flickr.parse_response(
        self.flickr.get(
          self.flickr.url(method=self.methodName, **args)))


class Flipy(object):
  def __init__(self, api_key, secret=None, token=None):
    self.default_args = {'api_key': api_key}
    self.secret = secret
    self.token = token

  def __getattr__(self, key):
    return Method(self, 'flickr.'+key)

  def __url(self, base, **args):
    # collect and flatten arguments
    a = self.default_args.copy()
    # add an auth token if available
    if self.token:
      a['auth_token'] = self.token
    for k,v in args.items():
      if isinstance(v, list):
        a[k] = ','.join(v)
      else:
        a[k] = v
    # calculate a signature if we have an API secret
    if self.secret:
      # get args sorted by name
      items = a.items()
      items.sort(lambda x,y:cmp(x[0], y[0]))
      # hash the secret then the arguments
      hash = hashlib.md5()
      hash.update(self.secret)
      for k, v in items:
        hash.update(k + v)
      # add the has as an api_sig argument
      a['api_sig'] = hash.hexdigest()
    return base + '?' + urlencode(a)

  def url(self, **args):
    return self.__url('http://flickr.com/services/rest', **args)
  def authurl(self, **args):
    return self.__url('http://flickr.com/services/auth', **args)

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
  me_info = flickr.people.getInfo(user_id=me.nsid)
  print 'My name is %s. I have %s photos at %s.' % (
    me_info.realname, me_info.photos.count, me_info.photosurl
  )
