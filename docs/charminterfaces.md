# Writing charm interfaces

For Charms to communicate with one another charms utilise what are called Interfaces.

Interfaces are the spin which charms use to enable communication between relationships, if you read the [Charm Writing Guide](./charmsindetail.md#what%20are%20interfaces) then you will have seen some illustrations on how charms communicate with each other.

There are two components to Charm Interfaces:

- Clients
- Servers (TODO: Should this be servers??) (TODO: Check Naming)

Interfaces take a structure much like charms themselves, but taking on different roles. In the case of interfaces they are 'facilitators'. Making sure that the communication between two charms takes an expected (maybe standard) form.

As a case study, we can look at the MySQLClient charm. This charm uses a single file called `interface_mysql.py` which contains both the 
 

 