from itertools import product
import string
import urlparse
import re
import random
import os.path, sys, djcelery
from oscar.defaults import *
from django import forms
from django.forms.models import inlineformset_factory
from django.conf import settings
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.models import get_current_site
from django.core import validators
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError
from django.db.models import get_model
from django.utils.translation import ugettext_lazy as _
from oscar.core.loading import get_profile_class, get_class
from oscar.apps.customer.utils import get_password_reset_url, normalise_email
from oscar.apps.customer.forms import UserForm as Core_UserForm
from core.models import User

Dispatcher = get_class('customer.utils', 'Dispatcher')
CommunicationEventType = get_model('customer', 'communicationeventtype')
ProductAlert = get_model('customer', 'ProductAlert')
MyEventList = get_model('social', 'MyEvent')
WishList = get_model('wishlists', 'WishList')
Line = get_model('wishlists', 'Line')


def generate_username():
    uname = ''.join([random.choice(string.letters + string.digits + '_') for i in range(30)])
    try:
        User.objects.get(username=uname)
        return generate_username()
    except User.DoesNotExist:
        return uname


class PasswordResetForm(auth_forms.PasswordResetForm):
    """
    This form takes the same structure as its parent from django.contrib.auth
    """
    communication_type_code = "PASSWORD_RESET"

    def save(self, domain_override=None,
             subject_template_name='registration/password_reset_subject.txt',
             email_template_name='registration/password_reset_email.html',
             use_https=False, token_generator=default_token_generator,
             from_email=None, request=None, **kwargs):
        """
        Generates a one-use only link for resetting password and sends to the
        user.
        """
        site = get_current_site(request)
        if domain_override is not None:
            site.domain = site.name = domain_override
        for user in self.users_cache:
            # Build reset url
            reset_url = "%s://%s%s" % (
                'https' if use_https else 'http',
                site.domain,
                get_password_reset_url(user))
            ctx = {
                'user': user,
                'site': site,
                'reset_url': reset_url}
            messages = CommunicationEventType.objects.get_and_render(
                code=self.communication_type_code, context=ctx)
            Dispatcher().dispatch_user_messages(user, messages)


'login form'
class EmailAuthenticationForm(AuthenticationForm):
    """
    Extends the standard django AuthenticationForm, to support 75 character
    usernames. 75 character usernames are needed to support the EmailOrUsername
    auth backend.
    """
    username = forms.EmailField(label=_('Email Address'))
    redirect_url = forms.CharField(
        widget=forms.HiddenInput, required=False)

    def __init__(self, host, *args, **kwargs):
        self.host = host
        super(EmailAuthenticationForm, self).__init__(*args, **kwargs)

    def clean_redirect_url(self):
        if 'username' in self.cleaned_data:
            username = self.cleaned_data['username'].strip()
            url = User.objects.get(email=username)
            if url:
                if url.profile_url is not None:
                    url_pattern = '/' + str(url.profile_url) + '/'
                else:
                    url_pattern = '/' + str(url.username) + '/'
            if not url:
                return settings.LOGIN_REDIRECT_URL
            host = urlparse.urlparse(url.username)[1]
            if host and host != self.host:
                return settings.LOGIN_REDIRECT_URL
        if 'username' not in self.cleaned_data:
            url_pattern = '/'
        return url_pattern


class CommonPasswordValidator(validators.BaseValidator):
    # See http://www.smartplanet.com/blog/business-brains/top-20-most-common-passwords-of-all-time-revealed-8216123456-8216princess-8216qwerty/4519
    forbidden_passwords = [
        'password',
        '1234',
        '12345'
        '123456',
        '123456y',
        '123456789',
        'iloveyou',
        'princess',
        'monkey',
        'rockyou',
        'babygirl',
        'monkey',
        'qwerty',
        '654321',
        'dragon',
        'pussy',
        'baseball',
        'football',
        'letmein',
        'monkey',
        '696969',
        'abc123',
        'qwe123',
        'qweasd',
        'mustang',
        'michael',
        'shadow',
        'master',
        'jennifer',
        '111111',
        '2000',
        'jordan',
        'superman'
        'harley'
    ]
    message = _("Please choose a less common password")
    code = 'password'

    def __init__(self, password_file=None):
        self.limit_value = password_file

    def clean(self, value):
        return value.strip()

    def compare(self, value, limit):
        return value in self.forbidden_passwords

    def get_forbidden_passwords(self):
        if self.limit_value is None:
            return self.forbidden_passwords

'register form'
class EmailUserCreationForm(forms.ModelForm):
    email = forms.EmailField(label=_('Email address'))
    username = forms.CharField(label=_('Username'))
    password1 = forms.CharField(
        label=_('Password'), widget=forms.PasswordInput,
        validators=[validators.MinLengthValidator(6),
                    CommonPasswordValidator()])
    password2 = forms.CharField(
        label=_('Confirm password'), widget=forms.PasswordInput)
    redirect_url = forms.CharField(
        widget=forms.HiddenInput, required=False)

    class Meta:
        model = User
        fields = ('email', 'username')

    def __init__(self, host=None, *args, **kwargs):
        self.host = host
        super(EmailUserCreationForm, self).__init__(*args, **kwargs)

    def clean_email(self):
        email = normalise_email(self.cleaned_data['email'])
        if User._default_manager.filter(email=email).exists():
            raise forms.ValidationError(
                _("A user with that email address already exists."))
        return email

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1', '')
        password2 = self.cleaned_data.get('password2', '')
        if password1 != password2:
            raise forms.ValidationError(
                _("The two password fields didn't match."))
        return password2

    def clean_redirect_url(self):
        if 'username' in self.cleaned_data:
            username = self.cleaned_data['username'].strip()
            url_pattern = '/' + str(username) + '/'
        if 'username' not in self.cleaned_data:
            url_pattern = settings.LOGIN_REDIRECT_URL
        return url_pattern

    def save(self, commit=True):
        user = super(EmailUserCreationForm, self).save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        username = user.username
        if 'username' in [f.name for f in User._meta.fields]:
            user.username = username
        if commit:
            if not User.objects.filter(username=username):
                user.save()
        user.save()
        return user


class OrderSearchForm(forms.Form):
    date_from = forms.DateField(required=False, label=_("From"))
    date_to = forms.DateField(required=False, label=_("To"))
    order_number = forms.CharField(required=False, label=_("Order number"))

    def clean(self):
        if self.is_valid() and not any([self.cleaned_data['date_from'],
                                        self.cleaned_data['date_to'],
                                        self.cleaned_data['order_number']]):
            raise forms.ValidationError(_("At least one field is required."))
        return super(OrderSearchForm, self).clean()

    def description(self):
        if not self.is_bound or not self.is_valid():
            return _('All orders')
        date_from = self.cleaned_data['date_from']
        date_to = self.cleaned_data['date_to']
        order_number = self.cleaned_data['order_number']
        desc = None
        if date_from and date_to:
            desc = _('Orders placed between %(date_from)s and %(date_to)s') % {
                'date_from': date_from,
                'date_to': date_to}
        elif date_from:
            desc = _('Orders placed since %s') % date_from
        elif date_to:
            desc = _('Orders placed until %s') % date_to
        if order_number and desc is None:
            desc = _('Orders with order number containing %s') % order_number
        elif order_number and desc is not None:
            desc += _(' and order number containing %s') % order_number
        return desc

    def get_filters(self):
        date_from = self.cleaned_data['date_from']
        date_to = self.cleaned_data['date_to']
        order_number = self.cleaned_data['order_number']
        kwargs = {}
        if date_from and date_to:
            kwargs['date_placed__range'] = [date_from, date_to]
        elif date_from and not date_to:
            kwargs['date_placed__gt'] = date_from
        elif not date_from and date_to:
            kwargs['date_placed__lt'] = date_to
        if order_number:
            kwargs['number__contains'] = order_number
        return kwargs


class UserForm(Core_UserForm):
    profile_url = forms.CharField(widget=forms.TextInput(attrs={'placeholder': ''}),
                                  required=False, label=_("Profile URL"))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        kwargs['instance'] = user
        super(Core_UserForm, self).__init__(*args, **kwargs)
        if 'email' in self.fields:
            self.fields['email'].required = True

    def clean_email(self):
        """
        Make sure that the email address is aways unique as it is
        used instead of the username. This is necessary because the
        unique-ness of email addresses is *not* enforced on the model
        level in ``django.contrib.auth.models.User``.
        """
        email = normalise_email(self.cleaned_data['email'])
        if User._default_manager.filter(
                email=email).exclude(id=self.user.id).exists():
            raise ValidationError(
                _("A user with this email address already exists"))
        return email

    def clean_profile_url(self):
        from context_processors import PROJECT_URL
        profile_url = self.cleaned_data['profile_url']
        from oscar.app import application

        'check url in oscar core'
        core_url = str(application.get_urls())
        if re.search(profile_url, core_url) is None:
            pass
        else:
            raise ValidationError(_("Your URL conflict with the system URL. Please choose another URL"))

        'check url in this project'
        root_url = str(PROJECT_URL.urlpatterns)
        if re.search(profile_url, root_url) is None:
            pass
        else:
            raise ValidationError(_("Your URL conflict with the system URL. Please choose another URL"))

        if len(User.objects.filter(profile_url=profile_url)) != 0:
            if len(profile_url) != 0:
                raise ValidationError(
                    _("A user with this Profile URL address already exists"))
        return profile_url

    class Meta:
        model = User
        fields = {'username', 'first_name', 'last_name', 'email', 'profile_url'}


Profile = get_profile_class()
if Profile:

    class UserAndProfileForm(forms.ModelForm):
        email = forms.EmailField(label=_('Email address'), required=True)

        def __init__(self, user, *args, **kwargs):
            self.user = user
            try:
                instance = Profile.objects.get(user=user)
            except ObjectDoesNotExist:
                # User has no profile, try a blank one
                instance = Profile(user=user)
            kwargs['instance'] = instance

            super(UserAndProfileForm, self).__init__(*args, **kwargs)

            # Get a list of profile fields to help with ordering later
            profile_field_names = self.fields.keys()
            del profile_field_names[profile_field_names.index('email')]

            self.fields['email'].initial = self.instance.user.email

            # Add user fields (we look for core user fields first)
            core_field_names = set([f.name for f in User._meta.fields])
            user_field_names = ['email']
            for field_name in ('first_name', 'last_name'):
                if field_name in core_field_names:
                    user_field_names.append(field_name)
            user_field_names.extend(User._meta.additional_fields)

            # Store user fields so we know what to save later
            self.user_field_names = user_field_names

            # Add additional user fields
            additional_fields = forms.fields_for_model(
                User, fields=user_field_names)
            self.fields.update(additional_fields)

            # Set initial values
            for field_name in user_field_names:
                self.fields[field_name].initial = getattr(user, field_name)

            # Ensure order of fields is email, user fields then profile fields
            self.fields.keyOrder = user_field_names + profile_field_names

        class Meta:
            model = Profile
            fields = {'username', 'email', 'date_joined'}

        def clean_email(self):
            email = normalise_email(self.cleaned_data['email'])
            if User._default_manager.filter(
                    email=email).exclude(id=self.user.id).exists():
                raise ValidationError(
                    _("A user with this email address already exists"))
            return email

        def save(self, *args, **kwargs):
            user = self.instance.user

            # Save user also
            for field_name in self.user_field_names:
                setattr(user, field_name, self.cleaned_data[field_name])
            user.save()

            return super(ProfileForm, self).save(*args, **kwargs)

    ProfileForm = UserAndProfileForm
else:
    ProfileForm = UserForm


class ProductAlertForm(forms.ModelForm):
    email = forms.EmailField(required=True, label=_(u'Send notification to'),
                             widget=forms.TextInput(attrs={
                                 'placeholder': _('Enter your email')
                             }))

    def __init__(self, user, product, *args, **kwargs):
        self.user = user
        self.product = product
        super(ProductAlertForm, self).__init__(*args, **kwargs)

        # Only show email field to unauthenticated users
        if user and user.is_authenticated():
            self.fields['email'].widget = forms.HiddenInput()
            self.fields['email'].required = False

    def save(self, commit=True):
        alert = super(ProductAlertForm, self).save(commit=False)
        if self.user.is_authenticated():
            alert.user = self.user
        alert.product = self.product
        if commit:
            alert.save()
        return alert

    def clean(self):
        cleaned_data = self.cleaned_data
        email = cleaned_data.get('email')
        if email:
            try:
                ProductAlert.objects.get(
                    product=self.product, email=email,
                    status=ProductAlert.ACTIVE)
            except ProductAlert.DoesNotExist:
                pass
            else:
                raise forms.ValidationError(_(
                    "There is already an active stock alert for %s") % email)
        elif self.user.is_authenticated():
            try:
                ProductAlert.objects.get(product=self.product,
                                         user=self.user,
                                         status=ProductAlert.ACTIVE)
            except ProductAlert.DoesNotExist:
                pass
            else:
                raise forms.ValidationError(_(
                    "You already have an active alert for this product"))
        return cleaned_data

    class Meta:
        model = ProductAlert
        exclude = ('user', 'key',
                   'status', 'date_confirmed', 'date_cancelled', 'date_closed',
                   'product')


class MyEventListForm(forms.ModelForm):

    def __init__(self, user, *args, **kwargs):
        super(MyEventListForm, self).__init__(*args, **kwargs)
        self.instance.owner = user

    class Meta:
        model = MyEventList
        fields = ('name', 'date_created', 'description')


class WishListLineForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(WishListLineForm, self).__init__(*args, **kwargs)
        self.fields['quantity'].widget.attrs['class'] = 'input-mini'


LineFormset = inlineformset_factory(
    WishList, Line, fields=('quantity', ), form=WishListLineForm,
    extra=0, can_delete=False)
