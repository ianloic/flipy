'''Flipy - simple Flickr API wrapper
Copyright 2010 Ian McKellar <http://ian.mckellar.org/>
Flipy is Free Software under the terms of the GNU LGPL. See lgpl.txt.
'''

from urllib import urlencode, quote, urlopen
import lxml.etree as ET
import hashlib

class FlipyError(StandardError):
  pass


class FlipyFlickrError(FlipyError):
  '''Flickr returned an error'''
  def __init__(self, rsp):
    # create an exception based on a failure response
    assert rsp.get('stat') == 'fail'
    err = rsp.find('err')
    FlipyError.__init__(self, 'Error %s: %s' % 
        (err.get('code'), err.get('msg')))


class FlipyAttributeConflictError(FlipyError):
  '''There was an attribute conflict, please file a bug and tell us what 
  API call you were making'''
  pass


class Response(object):
  CUSTOM={}
  # what elements can contain multiple non-obvious children
  MULTIPLES={
      'activity': ('event',), # flickr.activity.*
      'iconsphoto': ('photo',), # flickr.collections.getInfo
      'collection': ('set', 'collection'), # flickr.collections.getTree
      'category': ('subcat', 'group'), # flickr.groups.browse
      'photo': (
        'exif', # flickr.photos.getExif
        'person', # flickr.photos.getFavorites
      ),
      'uploader': ('ticket',), # flickr.photos.upload.checkTickets
      'photoset': ('photo',), # flickr.photosets.getPhotos
      'cluster': ('tag',), # flickr.tags.getClusters
      'hottags': ('tag',), # flickr.tags.getHotList
      'tag': ('raw',), # flickr.tags.getListUserRaw
      'people': ('person',), # flickr.photos.people.getList
  }
  @classmethod
  def custom(klass, *tags):
    '''a decorator for defining custom responses'''
    def call(f): 
      for tag in tags: klass.CUSTOM[tag] = f
      return f
    return call

  @classmethod
  def get(klass, flickr, node):
    '''get a response wrapper for the supplied node'''
    # nodes without attributes or node children map to their text value
    if len(node.attrib) == 0 and len(node) == 0:
      return node.text
    # look for a custom response wrapper constructor
    if klass.CUSTOM.has_key(node.tag):
      constructor = klass.CUSTOM[node.tag]
    else:
      constructor = klass

    children = []

    # if this tag is plural work out what the singular is
    singular = None
    if node.tag.endswith('s'): singular = node.tag[:-1]

    # find attributes
    # start with the XML attributes
    attrs = dict(node.attrib)
    # look through the direct children
    for child in node.getchildren():
      if child.tag == singular:
        # handle singularized children
        children.append(Response.get(flickr, child))
      elif (Response.MULTIPLES.has_key(node.tag) and 
          child.tag in Response.MULTIPLES[node.tag]):
        # handle multiple child attributes
        if attrs.has_key(child.tag):
          if isinstance(attrs[child.tag], list):
            attrs[child.tag].append(Response.get(flickr, child))
          else:
            # if a non-list attr exists already that's a problem
            raise FlipyAttributeConflictError()
        else:
          attrs[child.tag] = [Response.get(flickr, child)]
      else:
        # handle single child attributes
        if attrs.has_key(child.tag):
          raise FlipyAttributeConflictError()
        attrs[child.tag] = Response.get(flickr, child)

    # create an object and return it
    return constructor(flickr, node.tag, attrs, children)
        

  def __init__(self, flickr, tag, attrs, children):
    '''create a response wrapper'''
    self.flickr = flickr
    self.__tag = tag
    self.__attrs = attrs
    self.__children = children

  def __reduce__(self):
    '''get state for pickling'''
    return (
        self.__class__,
        (self.flickr, self.__tag, self.__attrs, self.__children),
    )

  def __getattr__(self, key):
    '''get a response attribute'''
    if self.__attrs.has_key(key):
      return self.__attrs[key]
    else:
      return None

  def __repr__(self):
    '''human readable representation'''
    return '<%s>%s%s' % (self.__tag, repr(self.__attrs), repr(self.__children))

  def pprint(self, indent=0):
    '''basic pretty printing'''
    print '%s<%s>%s' % (' '*indent, self.__tag, repr(self.__attrs))
    for child in self.__children:
      if isinstance(child, Response): child.pprint(indent+2)
      else: print '%s%s' % (' '*indent, repr(child))

  def __getitem__(self, key):
    '''get a response item'''
    return self.__children[key]

  def __len__(self):
    '''how many items does this response have'''
    return len(self.__children)


@Response.custom('user')
class User(Response):
  '''wrap the <user> response with useful methods'''

  def photos(self, **args):
    '''Photos uploaded by this user'''
    args['user_id'] = self.nsid
    return self.flickr.photos.search.paginate(**args)

  def photosOf(self, **args):
    '''Photos of this user'''
    args['user_id'] = self.nsid
    return self.flickr.people.getPhotosOf.paginate(**args)


@Response.custom('photo', 'prevphoto', 'nextphoto')
class Photo(Response):
  '''wrap the <photo> response with useful methods'''
  def info(self):
    '''get full information about this photo'''
    args = {'photo_id': self.id}
    if self.secret: args['secret'] = self.secret
    return self.flickr.photos.getInfo(**args)

  def people(self):
    '''return all of the people in this photo'''
    return self.flickr.photos.people.getList(photo_id = self.id)


class Method(object):
  '''method wrapper'''
  CUSTOM={}
  @classmethod
  def custom(klass, *methodNames):
    '''a decorator for defining custom methods'''
    def call(f): 
      for methodName in methodNames: klass.CUSTOM[methodName] = f
    return call

  @classmethod
  def get(klass, flickr, methodName):
    '''get a method wrapper for the supplied name'''
    # look for a custom method wrapper constructor
    if klass.CUSTOM.has_key(methodName):
      return klass.CUSTOM[methodName](flickr, methodName)
    else:
      return klass(flickr, methodName)

  def __init__(self, flickr, methodName):
    self.flickr = flickr
    self.methodName = methodName

  def __getattr__(self, key):
    return Method.get(self.flickr, self.methodName+'.'+key)

  def __call__(self, **args):
    return self.flickr.parse_response(
        self.flickr.get(
          self.flickr.resturl(method=self.methodName, **args)))

  def paginate(self, **args):
    '''return all results for this method as a generator, 
    even if there's multiple pages'''

    args['page'] = 1
    while True:
      results = self(**args)
      for result in results:
        yield result
      if results.pages != None:
        # we have a "pages" attribute
        if results.page == results.pages:
          break
      elif results.has_next_page != None:
        # we have a "has_next_page" attribute
        if results.has_next_page != '1':
          break
      else:
        # we have no indication that there's paging in this response
        break
      args['page'] = args['page'] + 1


class Flipy(object):
  def __init__(self, api_key, secret=None, token=None):
    self.default_args = {'api_key': api_key}
    self.secret = secret
    self.token = token

  def __getstate__(self):
    '''get state for pickling'''
    return { 
        'default_args': self.default_args,
        'secret': self.secret,
        'token': self.token,
        }
  def __setstate__(self, state):
    '''set state from pickle'''
    self.default_args = state['default_args']
    self.secret = state['secret']
    self.token = state['token']

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

  def resturl(self, **args):
    return self.__url('http://flickr.com/services/rest', **args)
  def authurl(self, **args):
    return self.__url('http://flickr.com/services/auth', **args)

  def get(self, url):
    '''Do an HTTP get for the supplied @url, return the response as a string'''
    return urlopen(url).read()

  def parse_response(self, string):
    '''Parse a response string into objects'''
    node =  ET.fromstring(string)
    if node.get('stat') != 'ok':
      raise FlipyFlickrError(node)
    children = node.getchildren()
    if len(children) == 1:
      return Response.get(flickr, children[0])
    else:
      return [Response.get(flickr, c) for c in children]


if __name__ == '__main__':
  flickr = Flipy('7e472304ad52ebcc5a266463cd247ad3')
  me = flickr.people.findByUsername(username='ianloic')
  me_info = flickr.people.getInfo(user_id=me.nsid)
  print 'My name is %s. I have %s photos at %s.' % (
    me_info.realname, me_info.photos.count, me_info.photosurl
  )
