SELECT kategoriya, COUNT(*)
FROM mahsulotlar

GROUP BY kategoriya
HAVING COUNT(*) > 3