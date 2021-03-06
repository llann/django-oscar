from django.shortcuts import get_object_or_404
from django.views.generic import (TemplateView, ListView, DetailView,
                                  CreateView, UpdateView, DeleteView,
                                  FormView, RedirectView)
from django.core.urlresolvers import reverse, reverse_lazy
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseRedirect, Http404
from django.contrib import messages
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth import logout as auth_logout, login as auth_login
from django.contrib.sites.models import get_current_site
from django.conf import settings
from oscar.core.loading import get_model

from oscar.views.generic import PostActionMixin
from oscar.apps.customer.utils import get_password_reset_url
from oscar.core.loading import get_class, get_profile_class, get_classes
from oscar.core.compat import get_user_model
from . import signals

PageTitleMixin, RegisterUserMixin = get_classes(
    'customer.mixins', ['PageTitleMixin', 'RegisterUserMixin'])
Dispatcher = get_class('customer.utils', 'Dispatcher')
EmailAuthenticationForm, EmailUserCreationForm, OrderSearchForm = get_classes(
    'customer.forms', ['EmailAuthenticationForm', 'EmailUserCreationForm',
                       'OrderSearchForm'])
PasswordChangeForm = get_class('customer.forms', 'PasswordChangeForm')
ProfileForm, ConfirmPasswordForm = get_classes(
    'customer.forms', ['ProfileForm', 'ConfirmPasswordForm'])
UserAddressForm = get_class('address.forms', 'UserAddressForm')
Order = get_model('order', 'Order')
Line = get_model('basket', 'Line')
Basket = get_model('basket', 'Basket')
UserAddress = get_model('address', 'UserAddress')
Email = get_model('customer', 'Email')
UserAddress = get_model('address', 'UserAddress')
ProductAlert = get_model('customer', 'ProductAlert')
CommunicationEventType = get_model('customer', 'CommunicationEventType')

User = get_user_model()


# =======
# Account
# =======
class NothingView(RedirectView):
    url = settings.OSCAR_HOMEPAGE

class AccountSummaryView(RedirectView):
    """
    View that exists for legacy reasons and customisability. It commonly gets
    called when the user clicks on "Account" in the navbar, and can be
    overriden to determine to what sub-page the user is directed without
    having to change a lot of templates.
    """
    url = reverse_lazy(settings.OSCAR_ACCOUNTS_REDIRECT_URL)


class AccountRegistrationView(NothingView):
    pass


class AccountAuthView(NothingView):
    url = settings.LOGIN_URL


class LogoutView(RedirectView):
    url = settings.OSCAR_HOMEPAGE
    permanent = False

    def get(self, request, *args, **kwargs):
        auth_logout(request)
        response = super(LogoutView, self).get(request, *args, **kwargs)

        for cookie in settings.OSCAR_COOKIES_DELETE_ON_LOGOUT:
            response.delete_cookie(cookie)

        return response


# =============
# Profile
# =============

class ProfileView(PageTitleMixin, TemplateView):
    template_name = 'customer/profile/profile.html'
    page_title = _('Profile')
    active_tab = 'profile'

    def get_context_data(self, **kwargs):
        ctx = super(ProfileView, self).get_context_data(**kwargs)
        ctx['profile_fields'] = self.get_profile_fields(self.request.user)
        return ctx

    def get_profile_fields(self, user):
        field_data = []

        # Check for custom user model
        for field_name in User._meta.additional_fields:
            field_data.append(
                self.get_model_field_data(user, field_name))

        # Check for profile class
        profile_class = get_profile_class()
        if profile_class:
            try:
                profile = profile_class.objects.get(user=user)
            except ObjectDoesNotExist:
                profile = profile_class(user=user)

            field_names = [f.name for f in profile._meta.local_fields]
            for field_name in field_names:
                if field_name in ('user', 'id'):
                    continue
                field_data.append(
                    self.get_model_field_data(profile, field_name))

        return field_data

    def get_model_field_data(self, model_class, field_name):
        """
        Extract the verbose name and value for a model's field value
        """
        field = model_class._meta.get_field(field_name)
        if field.choices:
            value = getattr(model_class, 'get_%s_display' % field_name)()
        else:
            value = getattr(model_class, field_name)
        return {
            'name': getattr(field, 'verbose_name'),
            'value': value,
        }


class ProfileUpdateView(NothingView):
    pass


class ProfileDeleteView(NothingView):
    pass
   

class ChangePasswordView(NothingView):
    pass


# =============
# Email history
# =============

class EmailHistoryView(PageTitleMixin, ListView):
    context_object_name = "emails"
    template_name = 'customer/email/email_list.html'
    paginate_by = 20
    page_title = _('Email History')
    active_tab = 'emails'

    def get_queryset(self):
        return Email._default_manager.filter(user=self.request.user)


class EmailDetailView(PageTitleMixin, DetailView):
    """Customer email"""
    template_name = "customer/email/email_detail.html"
    context_object_name = 'email'
    active_tab = 'emails'

    def get_object(self, queryset=None):
        return get_object_or_404(Email, user=self.request.user,
                                 id=self.kwargs['email_id'])

    def get_page_title(self):
        """Append email subject to page title"""
        return u'%s: %s' % (_('Email'), self.object.subject)


# =============
# Order history
# =============

class OrderHistoryView(PageTitleMixin, ListView):
    """
    Customer order history
    """
    context_object_name = "orders"
    template_name = 'customer/order/order_list.html'
    paginate_by = 20
    model = Order
    form_class = OrderSearchForm
    page_title = _('Order History')
    active_tab = 'orders'

    def get(self, request, *args, **kwargs):
        if 'date_from' in request.GET:
            self.form = self.form_class(self.request.GET)
            if not self.form.is_valid():
                self.object_list = self.get_queryset()
                ctx = self.get_context_data(object_list=self.object_list)
                return self.render_to_response(ctx)
            data = self.form.cleaned_data

            # If the user has just entered an order number, try and look it up
            # and redirect immediately to the order detail page.
            if data['order_number'] and not (data['date_to'] or
                                             data['date_from']):
                try:
                    order = Order.objects.get(
                        number=data['order_number'], user=self.request.user)
                except Order.DoesNotExist:
                    pass
                else:
                    return HttpResponseRedirect(
                        reverse('customer:order',
                                kwargs={'order_number': order.number}))
        else:
            self.form = self.form_class()
        return super(OrderHistoryView, self).get(request, *args, **kwargs)

    def get_queryset(self):
        qs = self.model._default_manager.filter(user=self.request.user)
        if self.form.is_bound and self.form.is_valid():
            qs = qs.filter(**self.form.get_filters())
        return qs

    def get_context_data(self, *args, **kwargs):
        ctx = super(OrderHistoryView, self).get_context_data(*args, **kwargs)
        ctx['form'] = self.form
        return ctx


class OrderDetailView(PageTitleMixin, PostActionMixin, DetailView):
    model = Order
    active_tab = 'orders'

    def get_template_names(self):
        return ["customer/order/order_detail.html"]

    def get_page_title(self):
        """
        Order number as page title
        """
        return u'%s #%s' % (_('Order'), self.object.number)

    def get_object(self, queryset=None):
        return get_object_or_404(self.model, user=self.request.user,
                                 number=self.kwargs['order_number'])

    def do_reorder(self, order):  # noqa (too complex (10))
        """
        'Re-order' a previous order.

        This puts the contents of the previous order into your basket
        """
        # Collect lines to be added to the basket and any warnings for lines
        # that are no longer available.
        basket = self.request.basket
        lines_to_add = []
        warnings = []
        for line in order.lines.all():
            is_available, reason = line.is_available_to_reorder(
                basket, self.request.strategy)
            if is_available:
                lines_to_add.append(line)
            else:
                warnings.append(reason)

        # Check whether the number of items in the basket won't exceed the
        # maximum.
        total_quantity = sum([line.quantity for line in lines_to_add])
        is_quantity_allowed, reason = basket.is_quantity_allowed(
            total_quantity)
        if not is_quantity_allowed:
            messages.warning(self.request, reason)
            self.response = HttpResponseRedirect(
                reverse('customer:order-list'))
            return

        # Add any warnings
        for warning in warnings:
            messages.warning(self.request, warning)

        for line in lines_to_add:
            options = []
            for attribute in line.attributes.all():
                if attribute.option:
                    options.append({
                        'option': attribute.option,
                        'value': attribute.value})
            basket.add_product(line.product, line.quantity, options)

        if len(lines_to_add) > 0:
            self.response = HttpResponseRedirect(reverse('basket:summary'))
            messages.info(
                self.request,
                _("All available lines from order %(number)s "
                  "have been added to your basket") % {'number': order.number})
        else:
            self.response = HttpResponseRedirect(
                reverse('customer:order-list'))
            messages.warning(
                self.request,
                _("It is not possible to re-order order %(number)s "
                  "as none of its lines are available to purchase") %
                {'number': order.number})


class OrderLineView(PostActionMixin, DetailView):
    """Customer order line"""

    def get_object(self, queryset=None):
        order = get_object_or_404(Order, user=self.request.user,
                                  number=self.kwargs['order_number'])
        return order.lines.get(id=self.kwargs['line_id'])

    def do_reorder(self, line):
        self.response = HttpResponseRedirect(
            reverse('customer:order',
                    args=(int(self.kwargs['order_number']),)))
        basket = self.request.basket

        line_available_to_reorder, reason = line.is_available_to_reorder(
            basket, self.request.strategy)

        if not line_available_to_reorder:
            messages.warning(self.request, reason)
            return

        # We need to pass response to the get_or_create... method
        # as a new basket might need to be created
        self.response = HttpResponseRedirect(reverse('basket:summary'))

        # Convert line attributes into basket options
        options = []
        for attribute in line.attributes.all():
            if attribute.option:
                options.append({'option': attribute.option,
                                'value': attribute.value})
        basket.add_product(line.product, line.quantity, options)

        if line.quantity > 1:
            msg = _("%(qty)d copies of '%(product)s' have been added to your"
                    " basket") % {
                'qty': line.quantity, 'product': line.product}
        else:
            msg = _("'%s' has been added to your basket") % line.product

        messages.info(self.request, msg)


class AnonymousOrderDetailView(DetailView):
    model = Order
    template_name = "customer/anon_order.html"

    def get_object(self, queryset=None):
        # Check URL hash matches that for order to prevent spoof attacks
        order = get_object_or_404(self.model, user=None,
                                  number=self.kwargs['order_number'])
        if self.kwargs['hash'] != order.verification_hash():
            raise Http404()
        return order


# ------------
# Address book
# ------------

class AddressListView(PageTitleMixin, ListView):
    """Customer address book"""
    context_object_name = "addresses"
    template_name = 'customer/address/address_list.html'
    paginate_by = 40
    active_tab = 'addresses'
    page_title = _('Address Book')

    def get_queryset(self):
        """Return customer's addresses"""
        return UserAddress._default_manager.filter(user=self.request.user)


class AddressCreateView(PageTitleMixin, CreateView):
    form_class = UserAddressForm
    model = UserAddress
    template_name = 'customer/address/address_form.html'
    active_tab = 'addresses'
    page_title = _('Add a new address')

    def get_form_kwargs(self):
        kwargs = super(AddressCreateView, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super(AddressCreateView, self).get_context_data(**kwargs)
        ctx['title'] = _('Add a new address')
        return ctx

    def get_success_url(self):
        messages.success(self.request,
                         _("Address '%s' created") % self.object.summary)
        return reverse('customer:address-list')


class AddressUpdateView(PageTitleMixin, UpdateView):
    form_class = UserAddressForm
    model = UserAddress
    template_name = 'customer/address/address_form.html'
    active_tab = 'addresses'
    page_title = _('Edit address')

    def get_form_kwargs(self):
        kwargs = super(AddressUpdateView, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super(AddressUpdateView, self).get_context_data(**kwargs)
        ctx['title'] = _('Edit address')
        return ctx

    def get_queryset(self):
        return self.request.user.addresses.all()

    def get_success_url(self):
        messages.success(self.request,
                         _("Address '%s' updated") % self.object.summary)
        return reverse('customer:address-list')


class AddressDeleteView(PageTitleMixin, DeleteView):
    model = UserAddress
    template_name = "customer/address/address_delete.html"
    page_title = _('Delete address?')
    active_tab = 'addresses'
    context_object_name = 'address'

    def get_queryset(self):
        return UserAddress._default_manager.filter(user=self.request.user)

    def get_success_url(self):
        messages.success(self.request,
                         _("Address '%s' deleted") % self.object.summary)
        return reverse('customer:address-list')


class AddressChangeStatusView(RedirectView):
    """
    Sets an address as default_for_(billing|shipping)
    """
    url = reverse_lazy('customer:address-list')

    def get(self, request, pk=None, action=None, *args, **kwargs):
        address = get_object_or_404(UserAddress, user=self.request.user,
                                    pk=pk)
        #  We don't want the user to set an address as the default shipping
        #  address, though they should be able to set it as their billing
        #  address.
        if address.country.is_shipping_country:
            setattr(address, 'is_%s' % action, True)
        elif action == 'default_for_billing':
            setattr(address, 'is_default_for_billing', True)
        else:
            messages.error(request, _('We do not ship to this country'))
        address.save()
        return super(AddressChangeStatusView, self).get(
            request, *args, **kwargs)
