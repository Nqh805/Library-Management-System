alter table muontra
add constraint muontra_ibfk_2
foreign key (id_thanh_vien)
references thanhvien(id_thanh_vien)
on delete restrict
on update cascade;

