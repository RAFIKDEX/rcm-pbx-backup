import sys
import sqlite3
import re
from twisted.internet import reactor
from twisted.internet.protocol import ServerFactory
from ldaptor.protocols.ldap import ldapserver, ldaperrors, ldapsyntax
from ldaptor.protocols import pureldap

DB_PATH = '/root/RCM_7021/rcm_7021.db'

class PBXLDAPServer(ldapserver.LDAPServer):
    def handle_LDAPBindRequest(self, request, controls, reply):
        # Always allow bind for phones
        reply(pureldap.LDAPBindResponse(resultCode=ldaperrors.Success.resultCode))
        return None

    def handle_LDAPSearchRequest(self, request, controls, reply):
        baseObject = request.baseObject.decode('utf-8') if isinstance(request.baseObject, bytes) else str(request.baseObject)
        filter_str = request.filter.asText()
        
        search_query = ""
        m = re.search(r'=([^)]+)', filter_str)
        if m:
            search_query = m.group(1).replace('*', '').strip()

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT activate, sort_by FROM ldap_settings WHERE id=1")
        settings = c.fetchone()
        
        if not settings or not settings['activate']:
            reply(pureldap.LDAPSearchResultDone(resultCode=ldaperrors.Success.resultCode))
            conn.close()
            return None
            
        sort_by = settings['sort_by']
        
        c.execute("SELECT name, ext as number, '' as mobile, '' as other FROM extensions WHERE sync_ldap=1")
        internals = c.fetchall()
        
        c.execute("SELECT name, number, mobile, other FROM external_contacts WHERE sync_ldap=1")
        externals = c.fetchall()
        
        conn.close()
        
        all_contacts = [dict(r) for r in internals] + [dict(r) for r in externals]
        
        if sort_by == 'number':
            all_contacts.sort(key=lambda x: str(x['number']).lower())
        else:
            all_contacts.sort(key=lambda x: str(x['name']).lower())
            
        for contact in all_contacts:
            name = str(contact['name'] or '')
            number = str(contact['number'] or '')
            mobile = str(contact.get('mobile') or '')
            other = str(contact.get('other') or '')
            
            if search_query:
                if search_query.lower() not in name.lower() and search_query not in number and search_query not in mobile:
                    continue
                    
            dn = f"cn={name},{baseObject}"
            attributes = {
                'cn': [name.encode('utf-8')],
                'sn': [name.encode('utf-8')],
                'telephoneNumber': [number.encode('utf-8')],
            }
            if mobile:
                attributes['mobile'] = [mobile.encode('utf-8')]
            if other:
                attributes['other'] = [other.encode('utf-8')]
                
            entry = pureldap.LDAPSearchResultEntry(
                objectName=dn.encode('utf-8'),
                attributes=[(k.encode('utf-8'), v) for k, v in attributes.items()]
            )
            reply(entry)
            
        reply(pureldap.LDAPSearchResultDone(resultCode=ldaperrors.Success.resultCode))
        return None

class PBXLDAPFactory(ServerFactory):
    protocol = PBXLDAPServer

if __name__ == '__main__':
    reactor.listenTCP(389, PBXLDAPFactory())
    print("LDAP Server started on port 389")
    reactor.run()
