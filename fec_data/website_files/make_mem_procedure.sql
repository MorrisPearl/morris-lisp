delimiter //
create procedure insert_member(IN m_name varchar(60))
begin
insert into indiv_m
select
m.*,
d.name as fec_name, d.city as fec_city, d.state as fec_state,
d.employer as fec_employer, d.committee_id, trans_amount , trans_date
from
indiv d , ngp_contacts m
where d.name like m_name and m.match_name = m_name;
end//
