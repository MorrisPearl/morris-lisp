drop table ngp_contacts;

create table ngp_contacts (
last_name varchar(60),
first_name varchar(60),
city varchar(60),
state char(2),
match_name varchar(60),
priv integer,
pub integer,
mem integer,
prospect integer);

load data local infile '/home/patrioticmillionaires/ngp.file.csv' into  table ngp_contacts fields terminated by '|' lines terminated by '\r\n';



